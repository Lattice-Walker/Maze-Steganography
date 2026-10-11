"""Circle mazes: a centre cell surrounded by rings of cells.

You enter through a gap in the outer wall and the goal is the centre.  As one
area of a mixed map a circle is crossed instead, in through one gap and out
through another.  Cell j of a ring covers the angles from j to j + 1 times
``2 pi / cells``, measured clockwise from the right-hand side of the picture.
"""

from dataclasses import dataclass
from math import pi

from .spanning import LayeredTrees

MIN_RINGS = 2


def ring_sizes(rings):
    """How many cells the centre (one) and each ring has.

    The first ring has six.  After that a ring has twice the cells of the one
    inside it whenever they would otherwise be more than one and a half times
    as wide as a ring is deep, which keeps cells roughly square.
    """
    if rings < MIN_RINGS:
        raise ValueError(f"a circle maze needs at least {MIN_RINGS} rings")
    sizes = [1, 6]
    for k in range(2, rings + 1):
        cells = sizes[-1]
        sizes.append(2 * cells if 2 * pi * k / cells > 1.5 else cells)
    return sizes


def trees(rings):
    """The graph of a circle maze, one layer per ring from the centre out.

    Link j of ring k joins its cell j to the cell inside it; inner edge j
    joins cells j and j + 1 of the ring.
    """
    sizes = ring_sizes(rings)
    inner = [[]] + [[(j, (j + 1) % cells) for j in range(cells)] for cells in sizes[1:]]
    links = [[]] + [[(j * sizes[k - 1] // sizes[k], j) for j in range(sizes[k])]
                    for k in range(1, rings + 1)]
    return LayeredTrees(sizes, inner, links)


@dataclass
class CircleMaze:
    rings: int
    inward: list   # inward[k][j]: cell j of ring k opens onto the ring inside it
    around: list   # around[k][j]: cells j and j + 1 of ring k are connected
    entrance: int  # the cell of the outer ring whose outer wall is open
    exit: int = None  # a second such cell, when the circle is crossed
