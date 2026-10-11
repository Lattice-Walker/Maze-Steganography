import base64
import json
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from mazestego import web


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, body=None):
        request = urllib.request.Request(
            self.base + path, None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def finish(self, started):
        while True:
            state = self.call("/api/jobs/" + started["job"])[1]
            if "result" in state or "error" in state:
                return state
            time.sleep(0.02)

    def test_page(self):
        with urllib.request.urlopen(self.base + "/") as response:
            self.assertIn(b"<title>Maze steganography</title>", response.read())

    def test_capacity(self):
        self.assertEqual(self.call("/api/capacity?rows=8&cols=8"),
                         (200, {"bits": 95.7, "bytes": 11}))
        self.assertEqual(self.call("/api/capacity?rows=8&cols=999")[0], 400)
        self.assertEqual(self.call("/api/capacity?rows=x&cols=8")[0], 400)

    def test_encode_then_decode(self):
        status, started = self.call(
            "/api/encode", {"message": "héllo", "rows": 8, "cols": 9, "seed": "s"})
        self.assertEqual(status, 202)
        result = self.finish(started)["result"]
        self.assertEqual((result["what"], result["name"], result["used"]),
                         ("8×9 maze", "maze-8x9.png", 6))
        self.assertEqual(self.call("/api/jobs/" + started["job"])[0], 404)

        started = self.call("/api/decode", {"file": result["png"], "seed": "s"})[1]
        self.assertEqual(self.finish(started)["result"],
                         {"message": "héllo", "bytes": 6, "what": "8×9 maze"})

    def test_mixed_map(self):
        # A 4x5 area with a circle of three rings to its right.
        areas = [{"kind": "straight", "rows": 4, "cols": 5, "x": 0, "y": 4},
                 {"kind": "circle", "rings": 3, "x": 16, "y": 0}]
        status, found = self.call("/api/board-check", {"areas": areas})
        self.assertEqual(status, 200)
        self.assertGreater(found["bytes"], 10)
        self.assertEqual((found["joints"][0]["owner"], found["joints"][0]["side"]), (0, "right"))
        self.assertEqual(len(found["joints"][0]["edges"]), 2)
        held = found["bytes"]
        overlapping = [areas[0], {**areas[1], "x": 4}]
        self.assertEqual(self.call("/api/board-check", {"areas": overlapping}),
                         (200, {"problem": "areas 1 and 2 overlap; move them apart"}))
        self.assertEqual(self.call("/api/board-check", {"areas": areas[:1]})[0], 400)
        self.assertEqual(self.call("/api/board-check", {"areas": areas * 5})[0], 400)
        self.assertEqual(self.call(
            "/api/board-check", {"areas": [areas[0], {**areas[1], "rings": 99}]})[0], 400)
        unplaced = [{"kind": "straight", "rows": 4, "cols": 5}, areas[1]]
        self.assertIn("problem", self.call("/api/board-check", {"areas": unplaced})[1])
        self.assertIn("start", self.call("/api/board-check", {"areas": areas, "start": 999})[1]["problem"])

        started = self.call("/api/encode", {"areas": areas, "message": "two areas", "seed": "s"})[1]
        result = self.finish(started)["result"]
        self.assertEqual((result["what"], result["name"], result["used"], result["held"]),
                         ("mixed map of 2 areas", "mixed-map-2.png", 9, held))
        started = self.call("/api/decode", {"file": result["png"], "seed": "s"})[1]
        self.assertEqual(self.finish(started)["result"],
                         {"message": "two areas", "bytes": 9, "what": "mixed map of 2 areas"})
        status, refused = self.call("/api/encode", {"areas": overlapping, "message": ""})
        self.assertEqual(status, 400)
        self.assertIn("overlap", refused["error"])

    def test_circle(self):
        self.assertEqual(self.call("/api/circle-capacity?rings=6"),
                         (200, {"bits": 224.1, "bytes": 28, "cells": 139}))
        self.assertEqual(self.call("/api/circle-capacity?rings=1")[0], 400)
        self.assertEqual(self.call("/api/circle-capacity?rings=999")[0], 400)
        self.assertEqual(self.call("/api/encode", {"rings": 0, "message": ""})[0], 400)

        started = self.call("/api/encode", {"rings": 6, "message": "round", "seed": "s"})[1]
        result = self.finish(started)["result"]
        self.assertEqual((result["what"], result["name"], result["used"], result["held"]),
                         ("circle maze of 6 rings", "circle-maze-6.png", 5, 28))
        started = self.call("/api/decode", {"file": result["png"], "seed": "s"})[1]
        self.assertEqual(self.finish(started)["result"],
                         {"message": "round", "bytes": 5, "what": "circle maze of 6 rings"})

    def test_custom_map(self):
        shape = {"rows": 4, "cols": 8, "start": [0, 0], "end": [3, 7],
                 "mask": ["....####", "........", "..####..", "........"]}
        self.assertEqual(self.call("/api/map-capacity", shape),
                         (200, {"bits": 17.1, "bytes": 2, "cells": 24}))
        split = {**shape, "mask": ["...#...."] * 4}
        self.assertEqual(self.call("/api/map-capacity", split),
                         (200, {"problem": "the cells must form one connected area"}))
        self.assertEqual(self.call("/api/encode", {**split, "message": ""})[0], 400)
        self.assertEqual(self.call("/api/map-capacity", {**shape, "mask": ["."]})[0], 200)

        started = self.call("/api/encode", {**shape, "message": "hi", "seed": "s"})[1]
        result = self.finish(started)["result"]
        self.assertEqual((result["used"], result["held"]), (2, 2))
        started = self.call("/api/decode", {"file": result["png"], "seed": "s"})[1]
        self.assertEqual(self.finish(started)["result"],
                         {"message": "hi", "bytes": 2, "what": "4×8 map"})

        started = self.call("/api/encode", {**shape, "message": "", "start": [0, 7]})[1]
        self.assertIn("start must be on a cell", self.finish(started)["error"])

    def test_errors(self):
        started = self.call("/api/encode", {"message": "x" * 99, "rows": 3, "cols": 3})[1]
        self.assertIn("does not fit", self.finish(started)["error"])
        started = self.call("/api/decode", {"file": base64.b64encode(b"junk").decode()})[1]
        self.assertIn("not a text maze", self.finish(started)["error"])
        self.assertEqual(self.call("/api/encode", {"message": "x", "rows": 0, "cols": 3})[0], 400)
        self.assertEqual(self.call("/api/decode", {"file": "%%%"})[0], 400)
        self.assertEqual(self.call("/api/nope", {})[0], 404)

    def test_without_a_server(self):
        ask = lambda *args: json.loads(web.answer(*args))
        self.assertEqual(ask("/api/capacity?rows=8&cols=8"), {"bits": 95.7, "bytes": 11})
        self.assertEqual(ask("/api/circle-capacity?rings=6")["bytes"], 28)
        self.assertIn("between", ask("/api/capacity?rows=8&cols=999")["error"])
        self.assertEqual(ask("/api/nope", "{}"), {"error": "Not found."})
        self.assertEqual(ask("/api/map-capacity", json.dumps({"rows": 1, "cols": 2, "mask": [".#"]})),
                         {"problem": "the map needs a start and an end"})

        steps = []
        result = ask("/api/encode", json.dumps({"message": "héllo", "rows": 8, "cols": 9, "seed": "s"}),
                     lambda done, total: steps.append(done / total))
        self.assertEqual((result["what"], result["used"], result["held"]), ("8×9 maze", 6, 13))
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(steps[-1], 1)
        self.assertEqual(ask("/api/decode", json.dumps({"file": result["png"], "seed": "s"})),
                         {"message": "héllo", "bytes": 6, "what": "8×9 maze"})
        self.assertIn("does not fit", ask("/api/encode", '{"message": "long", "rows": 2, "cols": 2}')["error"])
        self.assertIn("error", ask("/api/decode", '{"file": "%%%"}'))

    def test_browser_files(self):
        # The page run from GitHub Pages fetches the package file by file.
        package = Path(web.__file__).parent
        listed = re.search(r"MODULES = (\[.*?\]);", (package / "worker.js").read_text()).group(1)
        self.assertEqual(set(json.loads(listed)),
                         {path.stem for path in package.glob("*.py")} - {"cli", "__main__"})
        root = package.parent
        self.assertIn("mazestego/ui.html", (root / "index.html").read_text())
        # Without this Pages leaves out files that start with an underscore.
        self.assertTrue((root / ".nojekyll").exists())

    def test_cancel(self):
        started = self.call("/api/encode", {"message": "", "rows": 30, "cols": 30})[1]
        self.assertEqual(self.call(f"/api/jobs/{started['job']}/cancel", {})[0], 200)
        self.assertEqual(self.finish(started), {"error": "Cancelled."})


if __name__ == "__main__":
    unittest.main()
