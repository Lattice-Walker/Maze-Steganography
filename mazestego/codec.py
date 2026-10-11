"""Messages <-> mazes.

A plain rows x cols maze has ``trees * doors`` states: every perfect maze
times every way to open two segments of the outer wall.  A map, where some
cells are blocked and the start and end are chosen by hand, has one state per
perfect maze on the cells that are left.  A circle maze has one per perfect
maze and place for its entrance.  A mixed map is several areas, each a maze
of its own, so its states are every combination of theirs.  Byte strings,
ordered by length and
then lexicographically, are numbered 0, 1, 2, ... and state number
``scramble(n)`` holds string number ``n``.  Each state holds exactly one
string, so no capacity goes to headers or padding.

The scramble is a fixed pseudo-random bijection.  It is not encryption; it is
there so that every message, including an empty or repetitive one, lands on a
typical maze rather than on the degenerate ones that have small indices.
"""

import hashlib
from collections import namedtuple
from math import gcd, isqrt, log2

from . import circle
from .board import Board, Layout, default_places
from .circle import CircleMaze
from .maze import Maze
from .spanning import GridTrees, estimate_bits

Capacity = namedtuple("Capacity", "states bits bytes")


def _door_pairs(rows, cols):
    perimeter = 2 * (rows + cols)
    return perimeter * (perimeter - 1) // 2


def _grid_shape(rows, cols, blocked=None):
    """What tells one grid shape from another, for ``_scramble``."""
    cut = b"" if blocked is None else b"map" + bytes(
        (r, c) in blocked for r in range(rows) for c in range(cols)) + b"\0"
    return b"%dx%d\0" % (rows, cols) + cut


def _scramble(states, shape, seed):
    """Multiplier and offset of an affine bijection of range(states)."""
    size = (states.bit_length() + 64) // 8 + 1
    stream = hashlib.shake_256(b"mazestego/1 " + shape + seed).digest(2 * size)
    a = int.from_bytes(stream[:size], "big") % states
    b = int.from_bytes(stream[size:], "big") % states
    while gcd(a, states) != 1:
        a = (a + 1) % states
    return a, b


def _shorter(length):
    """How many byte strings are shorter than ``length``."""
    return (256 ** length - 1) // 255


def _guaranteed_bytes(states):
    length = 0
    while _shorter(length + 2) <= states:
        length += 1
    return length


def _number(message, states, what):
    number = _shorter(len(message)) + int.from_bytes(message, "big")
    if number >= states:
        raise ValueError(
            f"message of {len(message)} bytes does not fit in {what}, "
            f"which holds {_guaranteed_bytes(states)} bytes")
    return number


def capacity(rows, cols, blocked=None):
    """How much a rows x cols maze holds, or a map if ``blocked`` is given.
    Every message of up to ``bytes`` bytes fits; so do some that are one byte
    longer."""
    if blocked is None:
        states = GridTrees(rows, cols).count * _door_pairs(rows, cols)
    else:
        states = GridTrees(rows, cols, blocked).count
    return Capacity(states, log2(states), _guaranteed_bytes(states))


def _estimated_bytes(bits):
    # All strings of up to n bytes fit when (256**(n + 1) - 1) / 255 <= states.
    return max(0, int((bits + log2(255)) // 8) - 1)


def estimate_capacity(rows, cols, blocked):
    """``(bits, bytes)`` a map holds, from a floating-point count.  Quick
    enough to call while the map is being drawn; ``capacity`` is exact."""
    bits = estimate_bits(rows, cols, blocked)
    return bits, _estimated_bytes(bits)


def circle_capacity(rings):
    """How much a circle maze of ``rings`` rings holds, exactly."""
    states = circle.trees(rings).count * circle.ring_sizes(rings)[-1]
    return Capacity(states, log2(states), _guaranteed_bytes(states))


def estimate_circle_capacity(rings):
    """``(bits, bytes)`` a circle maze holds, from a floating-point count."""
    bits = circle.trees(rings).estimate_bits() + log2(circle.ring_sizes(rings)[-1])
    return bits, _estimated_bytes(bits)


def encode(message, rows, cols, seed=b"", progress=None):
    """The rows x cols maze that holds ``message`` (bytes)."""
    trees = GridTrees(rows, cols)
    states = trees.count * _door_pairs(rows, cols)
    number = _number(message, states, f"a {rows}x{cols} maze")
    a, b = _scramble(states, _grid_shape(rows, cols), seed)
    pair, index = divmod((a * number + b) % states, trees.count)
    down, right = trees.unrank(index, progress)
    hi = (1 + isqrt(8 * pair + 1)) // 2
    return Maze(rows, cols, down, right, (pair - hi * (hi - 1) // 2, hi))


def encode_map(message, rows, cols, blocked, start, end, seed=b"", progress=None):
    """The maze on the cells of a rows x cols grid outside ``blocked`` that
    holds ``message``, with ``start`` and ``end`` cells marked.

    The marks are yours to place, so unlike the doors of a plain maze they
    carry none of the message.
    """
    blocked = frozenset(map(tuple, blocked))
    start, end = tuple(start), tuple(end)
    for name, cell in (("start", start), ("end", end)):
        if not (0 <= cell[0] < rows and 0 <= cell[1] < cols) or cell in blocked:
            raise ValueError(f"the {name} must be on a cell of the maze")
    if start == end:
        raise ValueError("the start and the end must be different cells")
    trees = GridTrees(rows, cols, blocked)
    states = trees.count
    if states == 1:
        raise ValueError(
            "this shape allows only one maze, so it cannot hide anything; "
            "widen it somewhere or give it a loop")
    number = _number(message, states, "this map")
    a, b = _scramble(states, _grid_shape(rows, cols, blocked), seed)
    down, right = trees.unrank((a * number + b) % states, progress)
    return Maze(rows, cols, down, right, (), blocked, start, end)


def encode_circle(message, rings, seed=b"", progress=None):
    """The circle maze of ``rings`` rings that holds ``message``.

    Where the entrance sits on the outer wall carries part of the message;
    the goal is always the centre.
    """
    trees = circle.trees(rings)
    states = trees.count * trees.sizes[-1]
    number = _number(message, states, f"a circle maze of {rings} rings")
    a, b = _scramble(states, b"circle %d\0" % rings, seed)
    entrance, index = divmod((a * number + b) % states, trees.count)
    inward, around = trees.unrank(index, progress)
    return CircleMaze(rings, inward, around, entrance)


def _board_shape(layout):
    """What tells one board from another, for ``_scramble``."""
    return b"board " + repr((layout.areas, layout.places, layout.start, layout.end)).encode() + b"\0"


def _shared(progress, layout):
    """A progress callback for each area, sharing one bar by their work."""
    costs = [layout.cost(n) for n in range(len(layout.areas))]
    total, before = sum(costs), 0
    for cost in costs:
        yield progress and (lambda done, of, before=before, cost=cost:
                            progress(before * of + cost * done, total * of))
        before += cost


def estimate_board_capacity(areas, places=None, start=None, end=None):
    """``(bits, bytes)`` a mixed map holds.  Areas are ``("straight", rows,
    cols)`` or ``("circle", rings)``; see ``encode_board`` for the rest."""
    areas = list(areas)
    bits = Layout(areas, default_places(areas) if places is None else places,
                  start, end).estimate_bits()
    return bits, _estimated_bytes(bits)


def encode_board(message, areas, places=None, start=None, end=None, seed=b"", progress=None):
    """The mixed map that holds ``message``.

    ``areas`` lists the areas in the order the path crosses them, each
    ``("straight", rows, cols)`` or ``("circle", rings)``.  ``places`` gives
    the top-left corner ``(x, y)`` of each in half cells; without it they are
    put in a row.  ``start`` and ``end`` number the stretch of the first and
    last area's outer wall to leave open, and are chosen for you if left out.

    Where the areas sit and where the path starts and ends is yours to
    choose, so it carries none of the message.  The mazes do, and so does
    which lane the gate between each pair of neighbours is in.
    """
    areas = list(areas)
    layout = Layout(areas, default_places(areas) if places is None else places, start, end)
    states = layout.states()
    number = _number(message, states, "this mixed map")
    a, b = _scramble(states, _board_shape(layout), seed)
    state = (a * number + b) % states
    gates = []
    for joint in layout.joints:
        state, lane = divmod(state, joint.lanes)
        gates.append(lane)
    mazes = []
    for trees, share in zip(layout.trees, _shared(progress, layout)):
        state, index = divmod(state, trees.count)
        mazes.append(trees.unrank(index, share))
    return Board(layout.areas, layout.places, layout.start, layout.end, mazes, gates)


def decode(maze, seed=b"", progress=None):
    """The message (bytes) held by a maze of any kind."""
    if isinstance(maze, Board):
        layout = Layout(maze.areas, maze.places, maze.start, maze.end)
        states, state = 1, 0
        for joint, lane in zip(layout.joints, maze.gates):
            state += states * lane
            states *= joint.lanes
        for trees, tree, share in zip(layout.trees, maze.mazes, _shared(progress, layout)):
            state += states * trees.rank(*tree, share)
            states *= trees.count
        a, b = _scramble(states, _board_shape(layout), seed)
    elif isinstance(maze, CircleMaze):
        trees = circle.trees(maze.rings)
        states = trees.count * trees.sizes[-1]
        if maze.exit is not None or not 0 <= maze.entrance < trees.sizes[-1]:
            raise ValueError("a circle maze has one entrance, on its outer ring")
        state = maze.entrance * trees.count + trees.rank(maze.inward, maze.around, progress)
        a, b = _scramble(states, b"circle %d\0" % maze.rings, seed)
    elif maze.is_map:
        trees = GridTrees(maze.rows, maze.cols, maze.blocked)
        states = trees.count
        state = trees.rank(maze.down, maze.right, progress)
        a, b = _scramble(states, _grid_shape(maze.rows, maze.cols, maze.blocked), seed)
    else:
        rows, cols = maze.rows, maze.cols
        trees = GridTrees(rows, cols)
        states = trees.count * _door_pairs(rows, cols)
        lo, hi = maze.doors
        pair = hi * (hi - 1) // 2 + lo
        state = pair * trees.count + trees.rank(maze.down, maze.right, progress)
        a, b = _scramble(states, _grid_shape(rows, cols), seed)
    number = (state - b) * pow(a, -1, states) % states
    length = 0
    while _shorter(length + 1) <= number:
        length += 1
    return (number - _shorter(length)).to_bytes(length, "big")
