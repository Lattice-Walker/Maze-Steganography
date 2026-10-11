import math
import random
import unittest
from fractions import Fraction

from mazestego.spanning import GridTrees, estimate_bits


def kirchhoff(rows, cols, blocked):
    """The number of spanning trees, straight from the matrix-tree theorem."""
    cells = [(r, c) for r in range(rows) for c in range(cols) if (r, c) not in blocked]
    at = {cell: i for i, cell in enumerate(cells)}
    L = [[Fraction(0)] * len(cells) for _ in cells]
    for (r, c), a in at.items():
        for b in (at.get((r + 1, c)), at.get((r, c + 1))):
            if b is not None:
                L[a][a] += 1
                L[b][b] += 1
                L[a][b] -= 1
                L[b][a] -= 1
    M = [row[1:] for row in L[1:]]
    det = Fraction(1)
    for k in range(len(M)):
        pivot = next((i for i in range(k, len(M)) if M[i][k]), None)
        if pivot is None:
            return 0
        if pivot != k:
            M[k], M[pivot] = M[pivot], M[k]
            det = -det
        det *= M[k][k]
        for i in range(k + 1, len(M)):
            factor = M[i][k] / M[k][k]
            M[i] = [x - factor * y for x, y in zip(M[i], M[k])]
    return int(det)


def is_spanning_tree(rows, cols, down, right, blocked=()):
    for r, c in blocked:
        if (r and down[r - 1][c] or r + 1 < rows and down[r][c]
                or c and right[r][c - 1] or c + 1 < cols and right[r][c]):
            return False
    return _is_tree(rows, cols, down, right, rows * cols - len(blocked))


def _is_tree(rows, cols, down, right, cells):
    parent = list(range(rows * cols))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = [(r * cols + c, (r + 1) * cols + c)
             for r in range(rows - 1) for c in range(cols) if down[r][c]]
    edges += [(r * cols + c, r * cols + c + 1)
              for r in range(rows) for c in range(cols - 1) if right[r][c]]
    for a, b in edges:
        a, b = find(a), find(b)
        if a == b:
            return False
        parent[a] = b
    return len(edges) == cells - 1


class CountTest(unittest.TestCase):
    def test_known_counts(self):
        # Square values are OEIS A007341.
        known = {(1, 1): 1, (1, 5): 1, (5, 1): 1, (2, 2): 4, (2, 3): 15,
                 (3, 2): 15, (3, 3): 192, (3, 4): 2415, (4, 4): 100352,
                 (5, 5): 557568000, (6, 6): 32565539635200}
        for (rows, cols), count in known.items():
            self.assertEqual(GridTrees(rows, cols).count, count, (rows, cols))

    def test_count_is_symmetric(self):
        self.assertEqual(GridTrees(7, 11).count, GridTrees(11, 7).count)


class BijectionTest(unittest.TestCase):
    def test_every_index_is_a_distinct_tree(self):
        for rows, cols in [(1, 1), (1, 4), (4, 1), (2, 2), (2, 3), (3, 2),
                           (3, 3), (3, 4), (4, 3), (2, 6), (6, 2)]:
            trees = GridTrees(rows, cols)
            seen = set()
            for index in range(trees.count):
                down, right = trees.unrank(index)
                self.assertTrue(is_spanning_tree(rows, cols, down, right))
                seen.add((tuple(map(tuple, down)), tuple(map(tuple, right))))
                self.assertEqual(trees.rank(down, right), index)
            self.assertEqual(len(seen), trees.count, (rows, cols))

    def test_round_trip_on_larger_grids(self):
        rng = random.Random(1)
        for rows, cols in [(4, 4), (5, 9), (9, 5), (12, 12), (3, 25)]:
            trees = GridTrees(rows, cols)
            for index in [0, trees.count - 1] + [rng.randrange(trees.count) for _ in range(3)]:
                down, right = trees.unrank(index)
                self.assertTrue(is_spanning_tree(rows, cols, down, right))
                self.assertEqual(trees.rank(down, right), index)


SHAPES = {
    "ring": (7, 7, {(r, c) for r in range(2, 5) for c in range(2, 5)}),
    "U": (6, 7, {(r, c) for r in range(0, 4) for c in range(2, 5)}),
    "arch": (6, 7, {(r, c) for r in range(2, 6) for c in range(2, 5)}),
    "comb": (6, 9, {(r, c) for r in range(0, 4) for c in (1, 3, 5, 7)}),
    "wide U": (5, 12, {(r, c) for r in range(0, 3) for c in range(2, 10)}),
    "band": (8, 8, {(r, c) for r in range(8) for c in range(8) if abs(r - c) > 2}),
    "inset": (6, 6, {(r, c) for r in range(6) for c in range(6) if r in (0, 5) or c in (0, 5)}),
}


class ShapeTest(unittest.TestCase):
    def test_general_path_matches_full_grid_path(self):
        for rows, cols in [(1, 1), (1, 4), (4, 1), (2, 2), (3, 3), (3, 4), (4, 3)]:
            fast, slow = GridTrees(rows, cols), GridTrees(rows, cols)
            slow._uniform = False
            self.assertEqual(fast.count, slow.count)
            for index in range(fast.count):
                self.assertEqual(fast.unrank(index), slow.unrank(index), (rows, cols, index))

    def test_every_index_is_a_distinct_tree_on_random_shapes(self):
        rng = random.Random(4)
        checked = 0
        while checked < 25:
            rows, cols = rng.randint(1, 5), rng.randint(1, 5)
            blocked = {(r, c) for r in range(rows) for c in range(cols) if rng.random() < 0.3}
            try:
                trees = GridTrees(rows, cols, blocked)
            except ValueError:
                continue
            self.assertEqual(trees.count, kirchhoff(rows, cols, blocked), (rows, cols, blocked))
            if trees.count > 1500:
                continue
            seen = set()
            for index in range(trees.count):
                down, right = trees.unrank(index)
                self.assertTrue(is_spanning_tree(rows, cols, down, right, blocked))
                seen.add((tuple(map(tuple, down)), tuple(map(tuple, right))))
                self.assertEqual(trees.rank(down, right), index)
            self.assertEqual(len(seen), trees.count)
            checked += 1

    def test_named_shapes(self):
        rng = random.Random(5)
        for name, (rows, cols, blocked) in SHAPES.items():
            trees = GridTrees(rows, cols, blocked)
            self.assertEqual(trees.count, kirchhoff(rows, cols, blocked), name)
            self.assertAlmostEqual(estimate_bits(rows, cols, blocked),
                                   math.log2(trees.count), places=9, msg=name)
            for index in [0, trees.count - 1] + [rng.randrange(trees.count) for _ in range(3)]:
                down, right = trees.unrank(index)
                self.assertTrue(is_spanning_tree(rows, cols, down, right, blocked), name)
                self.assertEqual(trees.rank(down, right), index, name)

    def test_bad_shapes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "connected"):
            GridTrees(4, 4, {(r, 2) for r in range(4)})
        with self.assertRaisesRegex(ValueError, "every cell"):
            GridTrees(2, 2, {(r, c) for r in range(2) for c in range(2)})
        with self.assertRaisesRegex(ValueError, "outside"):
            GridTrees(2, 2, {(5, 5)})

    def test_passage_into_blocked_cell_is_rejected(self):
        trees = GridTrees(3, 3, {(1, 1)})
        down, right = trees.unrank(0)
        down[0][1] = True
        with self.assertRaisesRegex(ValueError, "blocked cell"):
            trees.rank(down, right)


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.trees = GridTrees(3, 3)
        self.down, self.right = self.trees.unrank(100)

    def test_index_out_of_range(self):
        for index in (-1, self.trees.count):
            with self.assertRaises(ValueError):
                self.trees.unrank(index)

    def test_loop_is_rejected(self):
        down = [[True] * 3 for _ in range(2)]
        right = [[True] * 2 for _ in range(3)]
        with self.assertRaisesRegex(ValueError, "loop"):
            self.trees.rank(down, right)

    def test_cut_off_cells_are_rejected(self):
        down = [[False] * 3 for _ in range(2)]
        right = [[False] * 2 for _ in range(3)]
        with self.assertRaisesRegex(ValueError, "cut off"):
            self.trees.rank(down, right)

    def test_wrong_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            GridTrees(3, 4).rank(self.down, self.right)


if __name__ == "__main__":
    unittest.main()
