import math
import random
import struct
import unittest
import zlib

from mazestego import (
    CircleMaze, circle_capacity, decode, encode, encode_circle,
    estimate_circle_capacity, from_png, to_png, to_text,
)
from mazestego import circle
from mazestego.render import _SIGNATURE, _chunk, _dark_pixels


def is_spanning_tree(trees, linked, lateral):
    first = [0]
    for size in trees.sizes:
        first.append(first[-1] + size)
    group = list(range(trees.cells))

    def find(a):
        while group[a] != a:
            group[a] = group[group[a]]
            a = group[a]
        return a

    joins = 0
    for s in range(len(trees.sizes)):
        pairs = [(first[s] + i, first[s] + j)
                 for (i, j), kept in zip(trees.inner[s], lateral[s]) if kept]
        pairs += [(first[s - 1] + i, first[s] + j)
                  for (i, j), kept in zip(trees.links[s], linked[s]) if kept]
        for a, b in pairs:
            a, b = find(a), find(b)
            if a == b:
                return False
            group[a] = b
            joins += 1
    return joins == trees.cells - 1


def enlarged_rgb_png(png, factor):
    """The picture as an RGB PNG, every pixel repeated ``factor`` times."""
    dark = _dark_pixels(png)
    rows = [bytes(d for d in row for _ in range(factor)) for row in dark for _ in range(factor)]
    raw = b"".join(b"\0" + b"".join(b"\x10\x20\x30" if d else b"\xf0\xe0\xd0" for d in row)
                   for row in rows)
    return (_SIGNATURE
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


class ShapeTest(unittest.TestCase):
    def test_ring_sizes(self):
        self.assertEqual(circle.ring_sizes(13),
                         [1, 6, 12, 24, 24, 24, 48, 48, 48, 48, 48, 48, 96, 96])
        with self.assertRaises(ValueError):
            circle.ring_sizes(1)

    def test_counts(self):
        # Checked against the matrix-tree theorem.
        self.assertEqual(circle.trees(2).count, 107794125)
        self.assertEqual(circle.trees(3).count, 15697902734218049625)

    def test_every_cell_has_one_cell_inside_it(self):
        trees = circle.trees(7)
        for k in range(1, 8):
            self.assertEqual([j for _, j in trees.links[k]], list(range(trees.sizes[k])))
            self.assertTrue(all(0 <= i < trees.sizes[k - 1] for i, _ in trees.links[k]))

    def test_indices_are_distinct_trees(self):
        rng = random.Random(8)
        for rings in (2, 3, 5):
            trees = circle.trees(rings)
            indices = [0, trees.count - 1] + [rng.randrange(trees.count) for _ in range(60)]
            seen = set()
            for index in indices:
                linked, lateral = trees.unrank(index)
                self.assertTrue(is_spanning_tree(trees, linked, lateral))
                self.assertEqual(trees.rank(linked, lateral), index)
                seen.add(str((linked, lateral)))
            self.assertEqual(len(seen), len(set(indices)))


class CodecTest(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(9)
        for rings in (2, 4, 7):
            held = circle_capacity(rings).bytes
            for message in [b"", b"\0", b"rnd", b"\xff" * held, rng.randbytes(held)]:
                maze = encode_circle(message, rings, seed=b"s")
                self.assertEqual(decode(maze, seed=b"s"), message)

    def test_entrance_carries_part_of_the_message(self):
        entrances = {encode_circle(bytes([b]), 3).entrance for b in range(40)}
        self.assertGreater(len(entrances), 10)

    def test_estimate_matches_exact_capacity(self):
        exact = circle_capacity(6)
        bits, held = estimate_circle_capacity(6)
        self.assertAlmostEqual(bits, exact.bits, places=9)
        self.assertEqual(held, exact.bytes)

    def test_message_too_long(self):
        with self.assertRaisesRegex(ValueError, "circle maze of 3 rings"):
            encode_circle(b"x" * 99, 3)

    def test_wrong_seed(self):
        self.assertNotEqual(decode(encode_circle(b"round", 5, seed=b"a"), seed=b"b"), b"round")


class PngTest(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(10)
        for rings in (2, 3, 6, 9, 13):
            maze = encode_circle(rng.randbytes(2), rings)
            for cell, wall in [(12, 4), (6, 2), (9, 3), (5, 5), (20, 3)]:
                self.assertEqual(from_png(to_png(maze, cell, wall)), maze, (rings, cell, wall))

    def test_every_entrance_reads_back(self):
        maze = encode_circle(b"", 3)
        for entrance in range(24):
            moved = CircleMaze(3, maze.inward, maze.around, entrance)
            self.assertEqual(from_png(to_png(moved)).entrance, entrance)

    def test_enlarged(self):
        maze = encode_circle(b"big", 6)
        for factor in (2, 3):
            self.assertEqual(from_png(enlarged_rgb_png(to_png(maze, 6, 2), factor)), maze)

    def test_centre_mark_reads_as_paper(self):
        png = to_png(encode_circle(b"", 4))
        dark = _dark_pixels(png)
        middle = len(dark) // 2
        self.assertEqual(dark[middle][middle], 0)

    def test_too_small_to_draw(self):
        with self.assertRaisesRegex(ValueError, "larger cell or wall"):
            to_png(encode_circle(b"", 8), cell=2, wall=1)

    def test_no_text_form(self):
        with self.assertRaisesRegex(ValueError, "PNG"):
            to_text(encode_circle(b"", 3))

    def test_grid_and_circle_are_told_apart(self):
        self.assertIsInstance(from_png(to_png(encode_circle(b"", 3))), CircleMaze)
        self.assertNotIsInstance(from_png(to_png(encode(b"", 5, 5))), CircleMaze)


if __name__ == "__main__":
    unittest.main()
