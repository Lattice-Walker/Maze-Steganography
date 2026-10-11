"""Mixed maps: straight and circle areas placed on a board and grown together.

An area is either straight (a rows x cols grid) or a circle of some number of
rings, and the path crosses them in a chosen order.  Where two neighbours face
each other, the straight one grows across the space between them: its rows
carry on as lanes that leave it squarely, bend, and land on the other area's
outer wall, one lane to each stretch of that wall.  The cells of those lanes
are part of the straight area's maze, so the maze runs unbroken from the
straight part into the bent part.  The wall the lanes land on is shared, and
exactly one stretch of it is open: that gate is the only way between the two
areas, so the route from the start to the end crosses every area in order.

Where the areas sit is up to whoever lays out the board, as are the start and
the end, so those carry none of the message.  The mazes do, and so does the
choice of which lane each gate is in.

Positions are in half cells; everything else is in cells.  A straight area
with its corner at (x, y) spans x..x+cols and y..y+rows, and a circle of R
rings has radius R + 1.
"""

from dataclasses import dataclass
from math import atan2, cos, hypot, log2, pi, sin

from . import circle
from .spanning import GridTrees

MIN_AREAS = 2
MAX_LANES_DEEP = 40


@dataclass
class Board:
    areas: list   # ("straight", rows, cols) or ("circle", rings), along the path
    places: list  # the corner (x, y) of each, in half cells
    start: int    # the open stretch of the first area's outer wall
    end: int      # the open stretch of the last area's outer wall
    mazes: list   # each area's passages: (down, right) or (inward, around)
    gates: list   # for each joint, the lane its gate is in


def straight(rows, cols):
    """The description of a straight area."""
    return ("straight", rows, cols)


def ring(rings):
    """The description of a circle area."""
    return ("circle", rings)


def parse_area(text):
    """An area from text such as ``8x12`` or ``circle6``."""
    try:
        if text.startswith("circle"):
            return ring(int(text[len("circle"):]))
        rows, cols = text.split("x")
        return straight(int(rows), int(cols))
    except ValueError:
        raise ValueError(
            f"{text!r} is not an area; write ROWSxCOLS or circleRINGS") from None


def area_text(area):
    return f"circle{area[1]}" if area[0] == "circle" else f"{area[1]}x{area[2]}"


def along(curve, t):
    """The point a fraction ``t`` of the way along a Bezier curve."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve
    u = 1 - t
    return (u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
            u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3)


# The sides of a straight area: which way is out, and where its stretches of
# wall start in the numbering shared with plain mazes (top, bottom, left, right).
SIDES = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}


class Shape:
    """One area where it has been placed."""

    def __init__(self, area, place):
        self.area = area
        self.round = area[0] == "circle"
        self.x, self.y = place[0] / 2, place[1] / 2
        if self.round:
            self.rings = area[1]
            self.radius = self.rings + 1
            self.cells = circle.ring_sizes(self.rings)[-1]
            self.width = self.height = 2 * self.radius
            self.gaps = self.cells
        else:
            _, self.rows, self.cols = area
            self.width, self.height = self.cols, self.rows
            self.gaps = 2 * (self.rows + self.cols)
        self.centre = (self.x + self.width / 2, self.y + self.height / 2)

    @property
    def box(self):
        """Left, top, right and bottom in half cells, with room for the wall."""
        x, y = round(2 * self.x), round(2 * self.y)
        return x, y, x + 2 * self.width + 2, y + 2 * self.height + 2

    def side(self, name):
        """The corners along a side of a straight area, first to last, and
        the number of its first stretch of wall."""
        if name in ("top", "bottom"):
            y = self.y + (self.rows if name == "bottom" else 0)
            return ([(self.x + c, y) for c in range(self.cols + 1)],
                    self.cols if name == "bottom" else 0)
        x = self.x + (self.cols if name == "right" else 0)
        return ([(x, self.y + r) for r in range(self.rows + 1)],
                2 * self.cols + (self.rows if name == "right" else 0))

    def side_of(self, index):
        """Which side of a straight area a stretch of its wall is on."""
        if index < 2 * self.cols:
            return "bottom" if index >= self.cols else "top"
        return "right" if index >= 2 * self.cols + self.rows else "left"

    def facing(self, point):
        """The side of a straight area that looks towards a point."""
        dx = (point[0] - self.centre[0]) / self.cols
        dy = (point[1] - self.centre[1]) / self.rows
        if abs(dx) >= abs(dy):
            return "right" if dx > 0 else "left"
        return "bottom" if dy > 0 else "top"

    def gap(self, index):
        """A stretch of outer wall: its two ends, its middle, and the
        direction pointing out of the area there."""
        if self.round:
            step = 2 * pi / self.cells
            ends = [self.on_circle(angle) for angle in (index * step, (index + 1) * step)]
            middle = (index + 0.5) * step
            return ends, self.on_circle(middle), (cos(middle), sin(middle))
        name = self.side_of(index)
        corners, first = self.side(name)
        a, b = corners[index - first], corners[index - first + 1]
        return [a, b], ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), SIDES[name]

    def on_circle(self, angle):
        return (self.centre[0] + self.radius * cos(angle),
                self.centre[1] + self.radius * sin(angle))


class Joint:
    """Where two neighbouring areas meet.

    The ``owner`` is the straight area that grows across; ``side`` is the
    side it grows from, ``lanes`` how many rows or columns of it carry on,
    and ``deep`` how many cells each lane is cut into.  ``curves`` are the
    lines between lanes, each from the owner's side to the wall it lands on.
    ``landing`` numbers the stretches of the other area's outer wall that the
    lanes land on, in lane order.
    """

    def __init__(self, shapes, first):
        a, b = shapes[first], shapes[first + 1]
        if a.round and b.round:
            raise ValueError(
                f"areas {first + 1} and {first + 2} are both circles; "
                "put a straight area between them")
        # The straight area with the shorter end grows across to the other.
        ends = {}
        for n, (shape, other) in enumerate(((a, b), (b, a))):
            if not shape.round:
                name = shape.facing(other.centre)
                ends[n] = (len(shape.side(name)[0]) - 1, name)
        own = min(ends, key=lambda n: (ends[n][0], n))
        self.owner, self.other = first + own, first + 1 - own
        self.lanes, self.side = ends[own]
        owner, other = shapes[self.owner], shapes[self.other]
        corners, _ = owner.side(self.side)
        out = SIDES[self.side]
        middle = ((corners[0][0] + corners[-1][0]) / 2, (corners[0][1] + corners[-1][1]) / 2)
        pair = f"areas {first + 1} and {first + 2}"

        if other.round:
            if 2 * self.lanes > other.cells:
                raise ValueError(
                    f"{pair}: the circle is too small for the end of the straight "
                    "area to wrap round it; give it more rings or the area a shorter end")
            step = 2 * pi / other.cells
            aim = atan2(middle[1] - other.centre[1], middle[0] - other.centre[0])
            begin = round(aim / step - self.lanes / 2)
            land = [other.on_circle((begin + n) * step) for n in range(self.lanes + 1)]
            outs = [(cos((begin + n) * step), sin((begin + n) * step))
                    for n in range(self.lanes + 1)]
            self.landing = [(begin + n) % other.cells for n in range(self.lanes)]
        else:
            self.other_side = other.facing(owner.centre)
            theirs, base = other.side(self.other_side)
            # Slide along that side to sit as squarely opposite as it can.
            across = theirs[-1][0] - theirs[0][0], theirs[-1][1] - theirs[0][1]
            length = len(theirs) - 1
            reach = ((middle[0] - theirs[0][0]) * across[0]
                     + (middle[1] - theirs[0][1]) * across[1]) / length
            begin = max(0, min(length - self.lanes, round(reach - self.lanes / 2)))
            land = theirs[begin:begin + self.lanes + 1]
            outs = [SIDES[self.other_side]] * (self.lanes + 1)
            self.landing = [base + begin + n for n in range(self.lanes)]

        # Lane 0 meets whichever end of the landing keeps the lanes from crossing.
        def spread(points):
            return sum(hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(corners, points))

        if spread(land[::-1]) < spread(land):
            land, outs, self.landing = land[::-1], outs[::-1], self.landing[::-1]
        far = spread(land) / (self.lanes + 1)
        towards = (sum(p[0] for p in land) / len(land) - middle[0],
                   sum(p[1] for p in land) / len(land) - middle[1])
        size = hypot(*towards) or 1
        mid_out = outs[len(outs) // 2]
        if (far < 0.75 or (towards[0] * out[0] + towards[1] * out[1]) / size < 0.35
                or -(towards[0] * mid_out[0] + towards[1] * mid_out[1]) / size < 0.35):
            raise ValueError(
                f"{pair} do not face each other squarely enough to be joined; "
                "move them apart a little, or more nearly side by side or one above the other")
        self.deep = max(1, min(MAX_LANES_DEEP, round(far)))
        self.curves = []
        for start, end, end_out in zip(corners, land, outs):
            pull = 0.4 * hypot(end[0] - start[0], end[1] - start[1])
            self.curves.append([start, (start[0] + pull * out[0], start[1] + pull * out[1]),
                                (end[0] + pull * end_out[0], end[1] + pull * end_out[1]), end])

    def corner(self, lane, depth):
        """The point ``depth`` cells out along the line before ``lane``."""
        return along(self.curves[lane], depth / self.deep)


class Layout:
    """A board worked out in full: its areas where they were placed, the
    joints between neighbours, and the grid each straight area has become
    now that it includes the lanes it grew.

    Raises ValueError, in words for whoever is laying out the board, if the
    areas cannot be joined where they are.
    """

    def __init__(self, areas, places, start=None, end=None):
        areas = [tuple(area) for area in areas]
        if len(areas) < MIN_AREAS:
            raise ValueError(f"a mixed map needs at least {MIN_AREAS} areas")
        if len(places) != len(areas):
            raise ValueError("every area needs a place on the board")
        for n, place in enumerate(places, 1):
            if len(place) != 2 or not all(isinstance(v, int) for v in place):
                raise ValueError(f"area {n} is not placed properly")
        self.areas, self.places = areas, [tuple(place) for place in places]
        self.shapes = [Shape(area, place) for area, place in zip(areas, places)]
        for i, a in enumerate(self.shapes):
            for j, b in enumerate(self.shapes[:i]):
                (al, at, ar, ab), (bl, bt, br, bb) = a.box, b.box
                if al < br and bl < ar and at < bb and bt < ab:
                    raise ValueError(f"areas {j + 1} and {i + 1} overlap; move them apart")
        self.joints = [Joint(self.shapes, n) for n in range(len(areas) - 1)]

        # What each stretch of each area's outer wall is taken up by.
        self.grown = [{} for _ in areas]   # side -> the joint that grows from it
        taken = [{} for _ in areas]        # stretch of wall -> the joint landing on it
        for joint in self.joints:
            both = f"area {joint.owner + 1} is joined to both its neighbours on the same side"
            if joint.side in self.grown[joint.owner]:
                raise ValueError(both + "; move one of them round to another side")
            self.grown[joint.owner][joint.side] = joint
            for index in joint.landing:
                if index in taken[joint.other]:
                    raise ValueError(
                        f"the two joints on area {joint.other + 1} run into each other; "
                        "move its neighbours further apart")
                taken[joint.other][index] = joint
        for n, shape in enumerate(self.shapes):
            if not shape.round:
                for index in taken[n]:
                    if shape.side_of(index) in self.grown[n]:
                        raise ValueError(
                            f"area {n + 1} is joined to both its neighbours on the same side; "
                            "move one of them round to another side")
        for joint in self.joints:
            self._check_clear(joint)

        # A straight area and its lanes fit a bigger grid with the corners cut off.
        self.frames, self.trees = [], []
        for n, shape in enumerate(self.shapes):
            if shape.round:
                self.frames.append(None)
                self.trees.append(circle.trees(shape.rings))
                continue
            deep = {name: joint.deep for name, joint in self.grown[n].items()}
            top, left = deep.get("top", 0), deep.get("left", 0)
            rows = top + shape.rows + deep.get("bottom", 0)
            cols = left + shape.cols + deep.get("right", 0)
            blocked = {(r, c) for r in range(rows) for c in range(cols)
                       if not top <= r < top + shape.rows and not left <= c < left + shape.cols}
            self.frames.append((top, left, rows, cols, frozenset(blocked)))
            self.trees.append(GridTrees(rows, cols, blocked))

        self.start = self._free_gap(0, start, "start")
        self.end = self._free_gap(len(areas) - 1, end, "end")

    def _check_clear(self, joint):
        """A joint must not run through an area."""
        for curve in (joint.curves[0], joint.curves[-1], joint.curves[len(joint.curves) // 2]):
            for step in range(1, 24):
                x, y = along(curve, step / 24)
                for n, shape in enumerate(self.shapes):
                    own = n in (joint.owner, joint.other)
                    if own and (step < 4 or step > 20):
                        continue
                    grow = -0.3 if own else 0.6
                    if shape.round:
                        inside = hypot(x - shape.centre[0], y - shape.centre[1]) < shape.radius + grow
                    else:
                        inside = (shape.x - grow < x < shape.x + shape.cols + grow
                                  and shape.y - grow < y < shape.y + shape.rows + grow)
                    if inside:
                        first = min(joint.owner, joint.other) + 1
                        raise ValueError(
                            f"the joint between areas {first} and {first + 1} runs through "
                            f"area {n + 1}; move the areas so that they face each other")

    def free_gaps(self, n):
        """The stretches of an area's outer wall that no joint uses."""
        shape = self.shapes[n]
        used = {index for joint in self.joints if joint.other == n for index in joint.landing}
        return [index for index in range(shape.gaps) if index not in used
                and (shape.round or shape.side_of(index) not in self.grown[n])]

    def _free_gap(self, n, index, name):
        """Check a start or end, or choose one: as far from the area's joint
        as the wall goes."""
        free = self.free_gaps(n)
        if index is None:
            joint = self.joints[0 if n == 0 else -1]
            meeting = joint.corner(joint.lanes // 2, 0 if joint.owner == n else joint.deep)
            index = max(free, key=lambda g: hypot(self.shapes[n].gap(g)[1][0] - meeting[0],
                                                  self.shapes[n].gap(g)[1][1] - meeting[1]))
        if not isinstance(index, int) or index not in free:
            raise ValueError(f"the {name} must be on a stretch of outer wall that is not part of a joint")
        return index

    # -- the grid a straight area has become ---------------------------------

    def corner(self, n, i, j):
        """Where corner (i, j) of straight area n's grid is on the board."""
        shape, (top, left, _, _, _) = self.shapes[n], self.frames[n]
        i, j = i - top, j - left    # counted from the corner of the area itself
        if j > shape.cols:
            return self.grown[n]["right"].corner(i, j - shape.cols)
        if j < 0:
            return self.grown[n]["left"].corner(i, -j)
        if i > shape.rows:
            return self.grown[n]["bottom"].corner(j, i - shape.rows)
        if i < 0:
            return self.grown[n]["top"].corner(j, -i)
        return shape.x + j, shape.y + i

    def edge(self, n, a, b):
        """The line between two neighbouring corners of area n's grid, as a
        run of points: straight, unless it follows a lane round a bend."""
        shape, (top, left, _, _, _) = self.shapes[n], self.frames[n]
        (i1, j1), (i2, j2) = a, b
        bend = None
        if i1 == i2:      # along a row
            if min(j1, j2) >= left + shape.cols:
                bend = self.grown[n]["right"], i1 - top, j1 - left - shape.cols, j2 - left - shape.cols
            elif max(j1, j2) <= left:
                bend = self.grown[n]["left"], i1 - top, left - j1, left - j2
        else:             # along a column
            if min(i1, i2) >= top + shape.rows:
                bend = self.grown[n]["bottom"], j1 - left, i1 - top - shape.rows, i2 - top - shape.rows
            elif max(i1, i2) <= top:
                bend = self.grown[n]["top"], j1 - left, top - i1, top - i2
        if bend is None:
            return [self.corner(n, *a), self.corner(n, *b)]
        joint, lane, d1, d2 = bend
        return [along(joint.curves[lane], (d1 + (d2 - d1) * t / 6) / joint.deep) for t in range(7)]

    def far_end(self, n, r, c, direction):
        """Whether the wall of cell (r, c) in ``direction`` is where a lane
        lands on the next area, which is that area's wall to draw."""
        top, left, rows, cols, _ = self.frames[n]
        return ((direction == "right" and c == cols - 1 and "right" in self.grown[n])
                or (direction == "left" and c == 0 and "left" in self.grown[n])
                or (direction == "bottom" and r == rows - 1 and "bottom" in self.grown[n])
                or (direction == "top" and r == 0 and "top" in self.grown[n]))

    def outer_gap(self, n, r, c, direction):
        """The number of the stretch of area n's own outer wall on this side
        of cell (r, c), or None if the cell is one of its lanes."""
        shape, (top, left, _, _, _) = self.shapes[n], self.frames[n]
        r, c = r - top, c - left
        if not (0 <= r < shape.rows and 0 <= c < shape.cols):
            return None
        return {"top": c, "bottom": shape.cols + c, "left": 2 * shape.cols + r,
                "right": 2 * shape.cols + shape.rows + r}[direction]

    def lattice(self, n):
        """Every wall area n's grid could have: ``(kind, r, c, points)``.

        ``kind`` is "down" or "across" for the wall between cell (r, c) and
        the one below it or to its right, and "top", "bottom", "left" or
        "right" for a wall of the cell with nothing of the area beyond it.
        """
        top, left, rows, cols, blocked = self.frames[n]

        def cell(r, c):
            return 0 <= r < rows and 0 <= c < cols and (r, c) not in blocked

        for r in range(rows):
            for c in range(cols):
                if not cell(r, c):
                    continue
                sides = {"top": ((r, c), (r, c + 1), (r - 1, c)),
                         "bottom": ((r + 1, c), (r + 1, c + 1), (r + 1, c)),
                         "left": ((r, c), (r + 1, c), (r, c - 1)),
                         "right": ((r, c + 1), (r + 1, c + 1), (r, c + 1))}
                for direction, (a, b, beyond) in sides.items():
                    if cell(*beyond):
                        if direction in ("bottom", "right"):
                            yield ("down" if direction == "bottom" else "across",
                                   r, c, self.edge(n, a, b))
                    elif not self.far_end(n, r, c, direction):
                        yield direction, r, c, self.edge(n, a, b)

    def sketch(self):
        """The lines of every joint, for showing a board before it has a
        maze: for each joint, the two outer lines of its lanes, then the
        lines between and across them.  Each line is a run of points."""
        found = []
        for joint in self.joints:
            lanes = [[along(curve, t / 12) for t in range(13)] for curve in joint.curves]
            across = [[joint.corner(lane, depth) for lane in range(joint.lanes + 1)]
                      for depth in range(1, joint.deep)]
            found.append({"edges": [lanes[0], lanes[-1]], "inside": lanes[1:-1] + across,
                          "owner": joint.owner, "side": joint.side})
        return found

    def states(self):
        """How many different boards this layout can hold."""
        total = 1
        for trees in self.trees:
            total *= trees.count
        for joint in self.joints:
            total *= joint.lanes
        return total

    def estimate_bits(self):
        """log2 of ``states`` without the slow exact counts."""
        return (sum(trees.estimate_bits() for trees in self.trees)
                + sum(log2(joint.lanes) for joint in self.joints))

    def cost(self, n):
        """Roughly how much work area n is, to share out a progress bar."""
        return sum(size ** 3 for size in self.trees[n].sizes)

    def open_gaps(self, n, gates):
        """The stretches of area n's outer wall that are open: the start or
        the end, and the gate of each joint that lands on it."""
        found = set()
        if n == 0:
            found.add(self.start)
        if n == len(self.areas) - 1:
            found.add(self.end)
        for joint, lane in zip(self.joints, gates):
            if joint.other == n:
                found.add(joint.landing[lane])
        return found


def default_places(areas):
    """The areas in a row, a little apart."""
    heights = [2 * (area[1] + 1) if area[0] == "circle" else area[1] for area in areas]
    places, x = [], 0
    for area, height in zip(areas, heights):
        width = 2 * (area[1] + 1) if area[0] == "circle" else area[2]
        places.append((x, max(heights) - height))
        x += 2 * width + 6
    return places
