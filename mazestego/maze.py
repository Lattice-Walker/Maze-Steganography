"""A maze as data: passages between cells, and how you get in and out.

There are two kinds.  A plain maze fills its rectangle and has two ``doors``,
openings in the outer wall.  A map has no doors: some cells may be
``blocked``, and a ``start`` and ``end`` cell are marked instead.
"""

from dataclasses import dataclass


@dataclass
class Maze:
    rows: int
    cols: int
    down: list    # down[r][c]: cells (r, c) and (r + 1, c) are connected
    right: list   # right[r][c]: cells (r, c) and (r, c + 1) are connected
    doors: tuple = ()               # plain: the two open outer wall segments, ascending
    blocked: frozenset = frozenset()  # map: cells that are not part of the maze
    start: tuple = None             # map: marked cells (row, col), if known
    end: tuple = None

    # Outer wall segments are numbered along the top edge (left to right),
    # then the bottom edge, then the left edge (top to bottom), then the right.

    @property
    def perimeter(self):
        return 2 * (self.rows + self.cols)

    @property
    def is_map(self):
        return not self.doors

    def walls(self):
        """``(h, v)``: h[r][c] is the wall above cell (r, c) (row ``rows`` is
        the bottom edge), v[r][c] the wall left of it (column ``cols`` is the
        right edge)."""
        rows, cols = self.rows, self.cols
        shut = [i not in self.doors for i in range(self.perimeter)]
        h = [shut[:cols]]
        h += [[not p for p in row] for row in self.down]
        h.append(shut[cols:2 * cols])
        v = [[shut[2 * cols + r]] + [not p for p in self.right[r]]
             + [shut[2 * cols + rows + r]] for r in range(rows)]
        return h, v

    @classmethod
    def from_walls(cls, h, v, blocked=frozenset(), start=None, end=None):
        """The maze with the given walls.  Two openings in the outer wall make
        a plain maze; none makes a map."""
        rows, cols = len(v), len(h[0])
        outer = h[0] + h[rows] + [row[0] for row in v] + [row[cols] for row in v]
        doors = tuple(i for i, wall in enumerate(outer) if not wall)
        if len(doors) not in (0, 2) or doors and (blocked or start or end):
            raise ValueError(
                "expected two openings in the outer wall, or none for a map; "
                f"found {len(doors)}")
        down = [[not w for w in row] for row in h[1:rows]]
        right = [[not w for w in row[1:cols]] for row in v]
        return cls(rows, cols, down, right, doors, frozenset(blocked), start, end)
