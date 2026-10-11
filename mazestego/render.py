"""Drawing mazes as PNG images or text, and reading them back."""

import struct
import zlib
from math import atan2, cos, hypot, pi, sin

from .board import Board, Layout
from .circle import MIN_RINGS, CircleMaze, ring_sizes
from .maze import Maze

# -- text --------------------------------------------------------------------


def to_text(maze):
    """The maze as text.  On a map, blocked cells are ``###`` and the start
    and end are marked ``S`` and ``E``."""
    if isinstance(maze, (CircleMaze, Board)):
        raise ValueError("a maze with circles cannot be written as text; save it as a PNG")
    h, v = maze.walls()

    def inside(r, c):
        if c == maze.cols:
            return ""
        if (r, c) in maze.blocked:
            return "###"
        return {maze.start: " S ", maze.end: " E "}.get((r, c), "   ")

    lines = []
    for r in range(maze.rows + 1):
        lines.append("+" + "".join(("---" if w else "   ") + "+" for w in h[r]))
        if r < maze.rows:
            lines.append("".join(("|" if w else " ") + inside(r, c)
                                 for c, w in enumerate(v[r])).rstrip())
    return "\n".join(lines) + "\n"


def from_text(text):
    # A corridor row with a door at each end is a blank line, so only the
    # blank lines around the maze can be dropped.
    lines = text.strip("\n").splitlines()
    rows, cols = (len(lines) - 1) // 2, (max(map(len, lines), default=0) - 1) // 4
    if rows < 1 or cols < 1 or len(lines) != 2 * rows + 1:
        raise ValueError("not a text maze")
    lines = [line.ljust(4 * cols + 1) for line in lines]
    h = [[lines[2 * r][4 * c + 2] == "-" for c in range(cols)]
         for r in range(rows + 1)]
    v = [[lines[2 * r + 1][4 * c] == "|" for c in range(cols + 1)]
         for r in range(rows)]
    inside = {(r, c): lines[2 * r + 1][4 * c + 2]
              for r in range(rows) for c in range(cols)}
    marks = {mark: cell for cell, mark in inside.items() if mark in "SE"}
    blocked = {cell for cell, mark in inside.items() if mark == "#"}
    return Maze.from_walls(h, v, blocked, marks.get("S"), marks.get("E"))


# -- PNG ---------------------------------------------------------------------

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


# Paper, ink, start mark and end mark.  The marks are light enough to read as
# paper, so they guide a person without changing the maze.  The sixteen
# colours from number 16 on are whites with a touch less blue, one for each
# value of half a byte: a mixed map writes its layout along its top edge in
# them, where a person sees nothing and a reader finds out where the areas are.
_NOTE = 16
_PALETTE = (bytes.fromhex("ffffff" "000000" "5fc28f" "f08a6c") + b"\xff" * 36
            + b"".join(bytes([255, 255, 255 - half_byte]) for half_byte in range(16)))


def to_png(maze, cell=12, wall=4):
    """A PNG with ``cell`` pixel wide corridors and ``wall`` pixel thick
    walls.  On a map, blocked cells are solid, the start is a green disc and
    the end an orange square.  A circle maze has the end mark at its centre."""
    if cell < 1 or wall < 1:
        raise ValueError("cell and wall sizes must be at least 1 pixel")
    if isinstance(maze, Board):
        image = _board_image(maze, cell, wall)
    elif isinstance(maze, CircleMaze):
        image = _circle_image(maze, cell, wall)
    else:
        image = _grid_image(maze, cell, wall)
    raw = b"".join(b"\0" + line for line in image)
    png = (_SIGNATURE
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", len(image[0]), len(image), 8, 3, 0, 0, 0))
           + _chunk(b"PLTE", _PALETTE)
           + _chunk(b"IDAT", zlib.compress(raw, 9))
           + _chunk(b"IEND", b""))
    if isinstance(maze, (CircleMaze, Board)):
        # Round and bent walls land on square pixels, so check the picture
        # reads back before handing it over.
        try:
            readable = from_png(png) == maze
        except ValueError:
            readable = False
        if not readable:
            raise ValueError(
                "this cannot be drawn readably at this size; use a larger cell or wall size"
                + (", or give the joints more room" if isinstance(maze, Board) else ""))
    return png


# Palette index -> 1 for ink, 0 for anything that reads as paper.
_INK = bytes([0, 1]) + bytes(254)


def _grid_image(maze, cell, wall):
    """Rows of palette indices for a rectangular maze or a map."""
    h, v = maze.walls()
    pitch = margin = cell + wall
    width = maze.cols * pitch + wall + 2 * margin
    height = maze.rows * pitch + wall + 2 * margin
    image = [bytearray(width) for _ in range(height)]

    def fill(r, c, down, across):
        x, y = margin + c * pitch, margin + r * pitch
        for line in image[y:y + down]:
            line[x:x + across] = b"\1" * across

    def mark(place, ink, round):
        if place is None:
            return
        size = cell - 2 * (cell // 5)
        x = margin + place[1] * pitch + wall + cell // 5
        y = margin + place[0] * pitch + wall + cell // 5
        for i, line in enumerate(image[y:y + size]):
            # Half the width of a disc at this height, or of the square.
            reach = (size * size / 4 - (i + 0.5 - size / 2) ** 2) ** 0.5 if round else size / 2
            left, right = int(size / 2 - reach + 0.5), int(size / 2 + reach + 0.5)
            line[x + left:x + right] = bytes([ink]) * (right - left)

    for r in range(maze.rows + 1):
        for c in range(maze.cols + 1):
            fill(r, c, wall, wall)
            if c < maze.cols and h[r][c]:
                fill(r, c, wall, pitch + wall)
            if r < maze.rows and v[r][c]:
                fill(r, c, pitch + wall, wall)
    for r, c in maze.blocked:
        fill(r, c, pitch + wall, pitch + wall)
    mark(maze.start, 2, True)
    mark(maze.end, 3, False)
    return image


def _circle_image(maze, cell, wall):
    """Rows of palette indices for a circle maze."""
    return _circle_pixels(maze.rings, maze.inward, maze.around, (maze.entrance, maze.exit),
                          cell, wall, goal=maze.exit is None)


def _circle_pixels(rings, inward, around, gaps, cell, wall, goal):
    """Rows of palette indices for the rings of a circle maze, with a margin
    of one pitch all round.

    Ring k lies between the circles of radius k and k + 1 pitches.  A pixel is
    ink if it is within half a wall of a closed stretch of circle, of a closed
    wall between two cells of a ring, or of a corner where walls can meet
    (corners are always drawn, as the posts of a grid are).
    """
    sizes = ring_sizes(rings)
    pitch, half, turn = cell + wall, wall / 2, 2 * pi
    rim = (rings + 1) * pitch
    size = 2 * rim + wall + 2 * pitch
    centre = size / 2
    image = [bytearray(size) for _ in range(size)]
    for y, line in enumerate(image):
        dy = y + 0.5 - centre
        span = (rim + half) ** 2 - dy * dy
        if span <= 0:
            continue
        for x in range(int(centre - span ** 0.5), int(centre + span ** 0.5) + 1):
            dx = x + 0.5 - centre
            r = hypot(dx, dy)
            angle = atan2(dy, dx) % turn
            k = int(r / pitch + 0.5)    # the nearest circle
            ring = int(r / pitch)       # the ring this pixel is in
            ink = False
            if 1 <= k <= rings + 1 and abs(r - k * pitch) <= half:
                step = turn / sizes[min(k, rings)]
                j = min(int(angle / step), sizes[min(k, rings)] - 1)
                ink = not inward[k][j] if k <= rings else j not in gaps
                if not ink:
                    corner = round(angle / step) * step
                    ink = hypot(dx - k * pitch * cos(corner),
                                dy - k * pitch * sin(corner)) <= half
            if not ink and 1 <= ring <= rings:
                step = turn / sizes[ring]
                side = round(angle / step)   # the nearest side of the cell
                if r * abs(sin(angle - side * step)) <= half:
                    ink = not around[ring][(side - 1) % sizes[ring]]
            if ink:
                line[x] = 1
            elif goal and r <= cell * 0.3:
                line[x] = 3
    return image


class _Frame:
    """Where the things on a board fall in a picture of it: the pixel for a
    point given in cells, and the corner each circle's rings are pasted at."""

    def __init__(self, layout, cell, wall, left, top):
        self.layout, self.cell, self.wall = layout, cell, wall
        self.pitch, self.left, self.top = cell + wall, left, top

    def pixel(self, point):
        return (self.left + self.wall / 2 + point[0] * self.pitch,
                self.top + self.wall / 2 + point[1] * self.pitch)

    def circle_corner(self, shape):
        """Top-left pixel of a circle's rings (a whole pixel, which the
        centre given in cells may not land on)."""
        x, y = self.pixel(shape.centre)
        reach = shape.radius * self.pitch + self.wall / 2
        return round(x - reach), round(y - reach)

    def on_circle(self, shape, radius, angle):
        """A pixel given as a distance in pitches and an angle from the
        centre of a circle, as its rings were actually pasted."""
        x, y = self.circle_corner(shape)
        reach = shape.radius * self.pitch + self.wall / 2
        return (x + reach + radius * self.pitch * cos(angle),
                y + reach + radius * self.pitch * sin(angle))

    def gap(self, n, index):
        """The pixel in the middle of a stretch of area n's outer wall."""
        shape = self.layout.shapes[n]
        if shape.round:
            return self.on_circle(shape, shape.radius, (index + 0.5) * 2 * pi / shape.cells)
        return self.pixel(shape.gap(index)[1])


def _middle(points):
    """The point half way along a run of points."""
    lengths = [hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]
    left = sum(lengths) / 2
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if left <= length:
            part = left / length if length else 0
            return a[0] + (b[0] - a[0]) * part, a[1] + (b[1] - a[1]) * part
        left -= length
    return points[-1]


def _note(board, cell, wall, left, top):
    """The layout of a board as bytes, for its picture to carry."""
    body = bytes([1, cell, wall]) + struct.pack(">hhHHB", left, top, board.start, board.end,
                                               len(board.areas))
    for area, (x, y) in zip(board.areas, board.places):
        sizes = (area[1], 0) if area[0] == "circle" else area[1:]
        body += struct.pack(">BBBhh", area[0] == "circle", *sizes, x, y)
    return b"MZ" + bytes([len(body)]) + body + struct.pack(">H", zlib.crc32(body) & 0xffff)


def _read_note(pixels):
    """The layout written along the top of a board's picture: ``(cell, wall,
    left, top, areas, places, start, end)``, or None if there is none."""
    half_bytes = []
    for pixel in pixels:
        if len(pixel) != 3 or pixel[0] != 255 or pixel[1] != 255 or pixel[2] < 240:
            break
        half_bytes.append(255 - pixel[2])
    note = bytes(16 * a + b for a, b in zip(half_bytes[::2], half_bytes[1::2]))
    if note[:2] != b"MZ" or len(note) < 5 + note[2]:
        return None
    body = note[3:3 + note[2]]
    if struct.pack(">H", zlib.crc32(body) & 0xffff) != note[3 + note[2]:5 + note[2]] or body[0] != 1:
        return None
    cell, wall = body[1], body[2]
    left, top, start, end, count = struct.unpack(">hhHHB", body[3:12])
    areas, places = [], []
    for n in range(count):
        round_, a, b, x, y = struct.unpack(">BBBhh", body[12 + 7 * n:19 + 7 * n])
        areas.append(("circle", a) if round_ else ("straight", a, b))
        places.append((x, y))
    return cell, wall, left, top, areas, places, start, end


def _board_image(board, cell, wall):
    """Rows of palette indices for a mixed map."""
    layout = Layout(board.areas, board.places, board.start, board.end)
    pitch, half = cell + wall, wall / 2
    last = len(layout.areas) - 1

    # Everything to draw, in cells: walls as runs of points, and the marks.
    walls = []
    for n, shape in enumerate(layout.shapes):
        if shape.round:
            continue
        down, right = board.mazes[n]
        open_ = layout.open_gaps(n, board.gates)
        for kind, r, c, points in layout.lattice(n):
            if kind == "down":
                shut = not down[r][c]
            elif kind == "across":
                shut = not right[r][c]
            else:
                shut = layout.outer_gap(n, r, c, kind) not in open_
            if shut:
                walls.append(points)
    marks = []
    for n, index, colour in ((0, layout.start, 2), (last, layout.end, 3)):
        _, (x, y), (out_x, out_y) = layout.shapes[n].gap(index)
        away = (half + 0.7 * cell) / pitch
        marks.append(((x + away * out_x, y + away * out_y), colour))

    # Fit the picture round it all, with a margin.
    xs = ([p[0] for points in walls for p in points] + [m[0][0] for m in marks]
          + [v for shape in layout.shapes for v in (shape.x, shape.x + shape.width)])
    ys = ([p[1] for points in walls for p in points] + [m[0][1] for m in marks]
          + [v for shape in layout.shapes for v in (shape.y, shape.y + shape.height)])
    margin = 2 * pitch
    left, top = margin - int(min(xs) * pitch), margin - int(min(ys) * pitch)
    frame = _Frame(layout, cell, wall, left, top)
    note = _note(board, cell, wall, left, top)
    width = max(int(max(xs) * pitch) + left + wall + margin, 2 * len(note))
    height = int(max(ys) * pitch) + top + wall + margin
    image = [bytearray(width) for _ in range(height)]

    def dot(x, y, reach, colour, square=False):
        for line_y in range(max(0, int(y - reach)), min(height, int(y + reach) + 1)):
            line = image[line_y]
            for at in range(max(0, int(x - reach)), min(width, int(x + reach) + 1)):
                if square or (at + 0.5 - x) ** 2 + (line_y + 0.5 - y) ** 2 <= reach * reach:
                    line[at] = colour

    for n, shape in enumerate(layout.shapes):
        if not shape.round:
            continue
        rings = _circle_pixels(shape.rings, *board.mazes[n], layout.open_gaps(n, board.gates),
                               cell, wall, goal=False)
        x, y = frame.circle_corner(shape)
        for line, row in zip(image[y:], rings[pitch:len(rings) - pitch]):
            for at, ink in enumerate(row[pitch:len(row) - pitch], x):
                if ink:
                    line[at] = ink
    reach = max(half, 0.75)
    for points in walls:
        points = [frame.pixel(point) for point in points]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            steps = int(2 * hypot(x1 - x0, y1 - y0)) + 1
            for step in range(steps + 1):
                dot(x0 + (x1 - x0) * step / steps, y0 + (y1 - y0) * step / steps, reach, 1)
    for point, colour in marks:
        dot(*frame.pixel(point), 0.3 * cell + 1, colour, square=colour == 3)
    for at, byte in enumerate(note):
        image[0][2 * at], image[0][2 * at + 1] = _NOTE + byte // 16, _NOTE + byte % 16
    return image


def _dark_pixels(data):
    """Decode a PNG into rows of bytes, 1 where the pixel is dark."""
    return _decode(data)[0]


def _decode(data):
    """Decode a PNG into rows of bytes, 1 where the pixel is dark, and the
    colours of its top row of pixels."""
    if data[:8] != _SIGNATURE:
        raise ValueError("not a PNG file")
    pos, header, palette, packed = 8, None, None, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            packed += body
    if header is None:
        raise ValueError("not a PNG file")
    width, height, depth, colour, _, _, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    packs = depth in (1, 2, 4) and colour in (0, 3)
    if channels is None or interlace or not (depth == 8 or packs):
        raise ValueError("unsupported PNG: 16-bit and interlaced images cannot be read")
    raw = zlib.decompress(packed)
    stride = (width * channels * depth + 7) // 8
    rows, prior, first = [], bytearray(stride), []
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if len(line) != stride:
            raise ValueError("truncated PNG")
        if kind == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif kind == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prior))
        elif kind == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + (left + prior[i]) // 2) & 255
        elif kind == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b, c = prior[i], prior[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc
                                      else b if pb <= pc else c)) & 255
        prior = line
        if packs:
            # Several pixels per byte: spread them out, grey scaled to 0..255.
            top = (1 << depth) - 1
            scale = 255 // top if colour == 0 else 1
            line = bytes((byte >> shift & top) * scale for byte in line
                         for shift in range(8 - depth, -1, -depth))[:width]
        px = [line[i:i + channels] for i in range(0, width * channels, channels)]
        if colour == 3:
            px = [palette[3 * p[0]:3 * p[0] + 3] for p in px]
        elif colour in (4, 6):  # transparent counts as background
            px = [p[:-1] if p[-1] >= 128 else b"\xff" for p in px]
        if not y:
            first = px
        rows.append(bytes(sum(p) < 128 * len(p) for p in px))
    return rows, first


def from_png(data):
    """Read back a maze drawn by ``to_png`` (at any cell and wall size)."""
    dark, first = _decode(data)
    note = _read_note(first)
    return _read_board(dark, note) if note else _read(dark)


def _read(dark):
    """The single maze in a picture given as rows of bytes, 1 for ink."""
    if not any(1 in line for line in dark):
        raise ValueError("no maze found in the image")
    maze = _read_one(dark, strict=True)
    if maze is None:
        raise ValueError("the image does not look like a maze drawn by mazestego")
    return maze


def _read_board(dark, note):
    """The mixed map in a picture, given the layout it carries.  Every wall
    is then at a known place, and is there or not."""
    cell, wall, left, top, areas, places, start, end = note
    layout = Layout(areas, places, start, end)
    frame = _Frame(layout, cell, wall, left, top)
    lost = ValueError("the picture of this mixed map has been changed and cannot be read")

    def ink(point):
        x, y = int(point[0]), int(point[1])
        if not (0 <= y < len(dark) and 0 <= x < len(dark[y])):
            raise lost
        return dark[y][x] == 1

    mazes = []
    for n, shape in enumerate(layout.shapes):
        if shape.round:
            maze = _circle_at(lambda r, angle: ink(frame.on_circle(shape, r / frame.pitch, angle)),
                              shape.rings, frame.pitch)
            if maze is None:
                raise lost
            mazes.append((maze.inward, maze.around))
            continue
        _, _, rows, cols, _ = layout.frames[n]
        down = [[False] * cols for _ in range(rows - 1)]
        right = [[False] * (cols - 1) for _ in range(rows)]
        for kind, r, c, points in layout.lattice(n):
            if kind in ("down", "across"):
                (down if kind == "down" else right)[r][c] = not ink(frame.pixel(_middle(points)))
        mazes.append((down, right))
    gates = []
    for joint in layout.joints:
        open_ = [lane for lane, index in enumerate(joint.landing)
                 if not ink(frame.gap(joint.other, index))]
        if len(open_) != 1:
            raise lost
        gates += open_
    return Board(layout.areas, layout.places, layout.start, layout.end, mazes, gates)


def _read_one(dark, strict=False):
    """The single maze in a picture, or None.  ``strict`` lets through the
    error that says what is wrong with a grid, instead of None."""
    inked = [y for y, line in enumerate(dark) if 1 in line]
    x0 = min(dark[y].find(1) for y in inked)
    x1 = max(dark[y].rfind(1) for y in inked)
    lines = [dark[y][x0:x1 + 1] for y in range(inked[0], inked[-1] + 1)]
    try:
        # A grid always has a post in its corner; a circle never reaches it.
        return _read_grid(lines) if lines[0][0] else _read_circle(lines)
    except ValueError:
        if strict:
            raise
        return None


def _read_grid(lines):
    # Along any row or column of pixels, the shortest stretch of ink is a wall
    # crossed side to side and the shortest gap between ink is one corridor.
    scans = lines + [bytes(column) for column in zip(*lines)]
    wall = min((len(run) for scan in scans for run in scan.split(b"\0") if run),
               default=0)
    cell = min((len(run) for scan in scans
                for run in scan.strip(b"\0").split(b"\1") if run), default=0)
    pitch = wall + cell
    rows, extra_y = divmod(len(lines) - wall, pitch or 1)
    cols, extra_x = divmod(len(lines[0]) - wall, pitch or 1)
    if not wall or not cell or extra_x or extra_y or rows < 1 or cols < 1:
        return None
    mid, half = wall + cell // 2, wall // 2
    h = [[bool(lines[r * pitch + half][c * pitch + mid])
          for c in range(cols)] for r in range(rows + 1)]
    v = [[bool(lines[r * pitch + mid][c * pitch + half])
          for c in range(cols + 1)] for r in range(rows)]
    blocked = {(r, c) for r in range(rows) for c in range(cols)
               if lines[r * pitch + mid][c * pitch + mid]}
    return Maze.from_walls(h, v, blocked)


def _read_circle(lines):
    height, width = len(lines), len(lines[0])
    edge = max(height, width) / 2    # from the centre to the outside of the outer wall

    def ink(r, angle):
        x, y = int(width / 2 + r * cos(angle)), int(height / 2 + r * sin(angle))
        return 0 <= x < width and 0 <= y < height and lines[y][x] == 1

    # A rough wall thickness, from lines to the centre that no wall between
    # cells can lie on: a third of the way across a cell however often the
    # rings divide.  The first ink on such a line is a circle crossed squarely.
    crossings = [0]
    for quarter in range(4):
        angle = (quarter + 2 / 9) * pi / 2
        r = edge
        while r > 0 and not ink(r, angle):
            r -= 0.25
        thick = 0.0
        while r > 0 and ink(r, angle):
            r -= 0.25
            thick += 0.25
        crossings.append(thick)
    walls = sorted({max(1, round(max(crossings)) + more) for more in (-1, 0, 1, 2)})
    # The picture does not say how many rings it has, so try each count, with
    # each wall thickness near the measured one, and keep the first whose
    # corners, cell middles and passages all make sense.
    rings = MIN_RINGS
    while edge / (rings + 1) > 2:
        for wall in walls:
            pitch = (edge - wall / 2) / (rings + 1)
            maze = _circle_at(ink, rings, pitch) if pitch > wall else None
            if maze is not None:
                return maze
        rings += 1
    return None


def _circle_at(ink, rings, pitch):
    """The circle maze of this many rings in the picture, or None if what is
    there does not fit one."""
    sizes = ring_sizes(rings)
    inward, around = [[]], [[]]
    if ink(0, 0):
        return None
    for k in range(1, rings + 2):
        cells = sizes[min(k, rings)]
        step = 2 * pi / cells
        if not all(ink(k * pitch, j * step) for j in range(cells)):
            return None     # a corner without its post
        open_ = [not ink(k * pitch, (j + 0.5) * step) for j in range(cells)]
        if k > rings:
            gaps = [j for j in range(cells) if open_[j]]
            if len(gaps) not in (1, 2):   # two when it is an area of a mixed map
                return None
            maze = CircleMaze(rings, inward, around, *gaps)
            return maze if _is_tree(maze, sizes) else None
        if any(ink((k + 0.5) * pitch, (j + 0.5) * step) for j in range(cells)):
            return None     # ink in the middle of a cell
        inward.append(open_)
        around.append([not ink((k + 0.5) * pitch, (j + 1) * step) for j in range(cells)])


def _is_tree(maze, sizes):
    """Whether the passages of a circle maze join every cell without a loop."""
    first = [0]
    for cells in sizes:
        first.append(first[-1] + cells)
    group = list(range(first[-1]))

    def find(a):
        while group[a] != a:
            group[a] = group[group[a]]
            a = group[a]
        return a

    joins = 0
    for k in range(1, maze.rings + 1):
        cells, within = sizes[k], sizes[k] // sizes[k - 1]
        pairs = [(first[k] + j, first[k - 1] + j // within)
                 for j in range(cells) if maze.inward[k][j]]
        pairs += [(first[k] + j, first[k] + (j + 1) % cells)
                  for j in range(cells) if maze.around[k][j]]
        for a, b in pairs:
            a, b = find(a), find(b)
            if a == b:
                return False
            group[a] = b
            joins += 1
    return joins == first[-1] - 1


# -- files -------------------------------------------------------------------


def save(maze, path, cell=12, wall=4):
    """Write a maze as a PNG, or as text if ``path`` ends in ``.txt``."""
    if str(path).lower().endswith(".txt"):
        with open(path, "w") as f:
            f.write(to_text(maze))
    else:
        with open(path, "wb") as f:
            f.write(to_png(maze, cell, wall))


def loads(data):
    """Read a maze from the bytes of a PNG or text file."""
    if data[:8] == _SIGNATURE:
        return from_png(data)
    return from_text(data.decode())


def load(path):
    """Read a maze written by ``save``."""
    with open(path, "rb") as f:
        return loads(f.read())
