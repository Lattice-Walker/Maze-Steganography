"""A local web interface: ``python -m mazestego serve``.

Encoding and decoding can take minutes, so each runs as a job on its own
thread; the page polls for progress and can cancel between rows.

Where the page is served as a plain file with no server behind it, as on
GitHub Pages, it runs this module in the browser instead and puts the same
requests to ``answer``.
"""

import base64
import json
import threading
import uuid
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import codec, render
from .board import MIN_AREAS, Board, Layout, ring, straight
from .circle import MIN_RINGS, CircleMaze, ring_sizes

# Above these, even working out the capacity takes long enough to stall the
# page; larger mazes are a job for the command line.
MAX_SIDE = 80
MAX_RINGS = 30
MAX_AREAS = 8
MAX_BODY = 32 * 1024 * 1024

_PAGE = Path(__file__).with_name("ui.html")
_jobs = {}


class _Cancelled(Exception):
    pass


def _start(work):
    """Run ``work(progress)`` on a thread and return the id to poll."""
    job = {"done": 0, "total": 1, "cancel": False}

    def progress(done, total):
        if job["cancel"]:
            raise _Cancelled
        job["done"], job["total"] = done, total

    def run():
        try:
            job["result"] = work(progress)
        except _Cancelled:
            job["error"] = "Cancelled."
        except ValueError as error:
            job["error"] = str(error)
        except Exception as error:
            job["error"] = f"Internal error: {error!r}"

    key = uuid.uuid4().hex
    _jobs[key] = job
    threading.Thread(target=run, daemon=True).start()
    return key


def _size(rows, cols):
    try:
        rows, cols = int(rows), int(cols)
    except (TypeError, ValueError):
        raise ValueError("rows and columns must be whole numbers") from None
    if not (1 <= rows <= MAX_SIDE and 1 <= cols <= MAX_SIDE):
        raise ValueError(f"rows and columns must be between 1 and {MAX_SIDE}")
    return rows, cols


@lru_cache(maxsize=256)
def _capacity(rows, cols):
    cap = codec.capacity(rows, cols)
    return {"bits": round(cap.bits, 1), "bytes": cap.bytes}


def _map(body):
    """The size, blocked cells, start and end of the map in a request.  The
    mask is one string per row, ``#`` for each blocked cell."""
    rows, cols = _size(body.get("rows"), body.get("cols"))
    mask = body.get("mask")
    if (not isinstance(mask, list) or len(mask) != rows
            or any(not isinstance(line, str) or len(line) != cols for line in mask)):
        raise ValueError("the map does not match its size")
    blocked = frozenset((r, c) for r, line in enumerate(mask)
                        for c, mark in enumerate(line) if mark == "#")
    try:
        start, end = (tuple(map(int, body[key])) for key in ("start", "end"))
        if len(start) != 2 or len(end) != 2:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("the map needs a start and an end") from None
    return rows, cols, blocked, start, end


def _map_capacity(body):
    rows, cols, blocked, _, _ = _map(body)
    bits, held = codec.estimate_capacity(rows, cols, blocked)
    return {"bits": round(bits, 1), "bytes": held, "cells": rows * cols - len(blocked)}


def _map_check(body):
    """Capacity for the page's meter.  A shape that cannot work is a normal
    thing to draw on the way to one that can, so it is an answer, not an error."""
    try:
        return _map_capacity(body)
    except ValueError as error:
        return {"problem": str(error)}


def _rings(rings):
    try:
        rings = int(rings)
    except (TypeError, ValueError):
        raise ValueError("rings must be a whole number") from None
    if not MIN_RINGS <= rings <= MAX_RINGS:
        raise ValueError(f"rings must be between {MIN_RINGS} and {MAX_RINGS}")
    return rings


@lru_cache(maxsize=64)
def _circle_capacity(rings):
    bits, held = codec.estimate_circle_capacity(rings)
    return {"bits": round(bits, 1), "bytes": held, "cells": sum(ring_sizes(rings))}


def _areas(body):
    """The mixed map in a request: its areas in the order the path crosses
    them, where each is placed, and its start and end if they were chosen.
    An area is ``{"kind": "straight", "rows": .., "cols": ..}`` or ``{"kind":
    "circle", "rings": ..}``, with ``x`` and ``y`` for its corner."""
    listed = body.get("areas")
    if not isinstance(listed, list) or not MIN_AREAS <= len(listed) <= MAX_AREAS:
        raise ValueError(f"a mixed map has between {MIN_AREAS} and {MAX_AREAS} areas")
    areas, places = [], []
    for area in listed:
        if not isinstance(area, dict):
            raise ValueError("an area is not described properly")
        if area.get("kind") == "circle":
            areas.append(ring(_rings(area.get("rings"))))
        else:
            areas.append(straight(*_size(area.get("rows"), area.get("cols"))))
        places.append((area.get("x"), area.get("y")))
    return areas, places, body.get("start"), body.get("end")


def _board_check(body):
    """What the page needs to show a board as it is being arranged: how much
    it holds, where its joints run, and where its start and end are, or what
    is wrong with it.  A board that cannot work is a normal thing to pass
    through while dragging areas about, so it is an answer, not an error."""
    areas, places, start, end = _areas(body)
    try:
        layout = Layout(areas, places, start, end)
    except ValueError as error:
        return {"problem": str(error)}
    bits = layout.estimate_bits()
    return {"bits": round(bits, 1), "bytes": codec._estimated_bytes(bits),
            "start": layout.start, "end": layout.end, "joints": layout.sketch()}


def _describe(maze):
    """What to call a maze, and what to call its file."""
    if isinstance(maze, Board):
        return f"mixed map of {len(maze.areas)} areas", f"mixed-map-{len(maze.areas)}.png"
    if isinstance(maze, CircleMaze):
        return f"circle maze of {maze.rings} rings", f"circle-maze-{maze.rings}.png"
    kind = "map" if maze.is_map else "maze"
    return f"{maze.rows}×{maze.cols} {kind}", f"{kind}-{maze.rows}x{maze.cols}.png"


def _encode(body):
    message = str(body.get("message", "")).encode()
    seed = str(body.get("seed", "")).encode()
    if "areas" in body:
        areas, places, start, end = _areas(body)
        held = codec.estimate_board_capacity(areas, places, start, end)[1]

        def build(progress):
            return codec.encode_board(message, areas, places, start, end, seed, progress)
    elif "rings" in body:
        rings = _rings(body["rings"])
        held = _circle_capacity(rings)["bytes"]

        def build(progress):
            return codec.encode_circle(message, rings, seed, progress)
    elif "mask" in body:
        rows, cols, blocked, start, end = _map(body)
        held = _map_capacity(body)["bytes"]

        def build(progress):
            return codec.encode_map(message, rows, cols, blocked, start, end, seed, progress)
    else:
        rows, cols = _size(body.get("rows"), body.get("cols"))
        held = None

        def build(progress):
            return codec.encode(message, rows, cols, seed, progress)

    def work(progress):
        maze = build(progress)
        what, name = _describe(maze)
        return {"png": base64.b64encode(render.to_png(maze)).decode(),
                "what": what, "name": name, "used": len(message),
                "held": _capacity(rows, cols)["bytes"] if held is None else held}

    return work


def _decode(body):
    data = base64.b64decode(str(body.get("file", "")), validate=True)
    seed = str(body.get("seed", "")).encode()

    def work(progress):
        maze = render.loads(data)
        if isinstance(maze, Board):
            if len(maze.areas) > MAX_AREAS:
                raise ValueError(f"a mixed map has at most {MAX_AREAS} areas here")
            for area in maze.areas:
                _rings(area[1]) if area[0] == "circle" else _size(*area[1:])
        elif isinstance(maze, CircleMaze):
            _rings(maze.rings)
        else:
            _size(maze.rows, maze.cols)
        message = codec.decode(maze, seed, progress)
        return {"message": message.decode("utf-8", "replace"), "bytes": len(message),
                "what": _describe(maze)[0]}

    return work


# The long requests: each checks its body, then returns the work to run.
_JOBS = {"/api/encode": _encode, "/api/decode": _decode}


def _ask(path, body=None):
    """The answer to one of the page's quick questions, or None if ``path``
    is not one."""
    url = urlparse(path)
    if body is None:
        query = parse_qs(url.query)
        if url.path == "/api/capacity":
            return _capacity(*_size(query.get("rows", [""])[0], query.get("cols", [""])[0]))
        if url.path == "/api/circle-capacity":
            return _circle_capacity(_rings(query.get("rings", [""])[0]))
    elif url.path == "/api/map-capacity":
        return _map_check(body)
    elif url.path == "/api/board-check":
        return _board_check(body)
    return None


def answer(path, body=None, progress=lambda done, total: None):
    """Answer one request with no server and no threads, taking the body as
    JSON and giving JSON back.  A job runs to its end before this returns,
    reporting to ``progress(done, total)`` on the way."""
    try:
        body = None if body is None else json.loads(body)
        if path in _JOBS:
            found = _JOBS[path](body)(progress)
        else:
            found = _ask(path, body)
            if found is None:
                found = {"error": "Not found."}
    except ValueError as error:
        found = {"error": str(error)}
    except Exception as error:
        found = {"error": f"Internal error: {error!r}"}
    return json.dumps(found)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, status, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _answer(self, found):
        if found is None:
            self._send(404, {"error": "Not found."})
        else:
            self._send(200, found)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/":
                self._send(200, _PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path.startswith("/api/jobs/"):
                key = url.path.rsplit("/", 1)[1]
                job = _jobs.get(key)
                if job is None:
                    self._send(404, {"error": "No such job."})
                elif "result" in job or "error" in job:
                    del _jobs[key]
                    self._send(200, {k: job[k] for k in ("result", "error") if k in job})
                else:
                    self._send(200, {"done": job["done"], "total": job["total"]})
            else:
                self._answer(_ask(self.path))
        except ValueError as error:
            self._send(400, {"error": str(error)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("that file is too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            if path in _JOBS:
                self._send(202, {"job": _start(_JOBS[path](body))})
            elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job = _jobs.get(path.split("/")[3])
                if job:
                    job["cancel"] = True
                self._send(200, {})
            else:
                self._answer(_ask(path, body))
        except ValueError as error:
            self._send(400, {"error": str(error)})


def serve(host="127.0.0.1", port=8000):
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"mazestego: serving on http://{host}:{port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
