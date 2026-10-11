import random
import struct
import unittest
import zlib

from mazestego import Maze, decode, encode, encode_map, from_png, from_text, to_png, to_text
from mazestego.render import _SIGNATURE, _chunk, _dark_pixels


def rgb_png(dark, filter_type):
    """An RGB PNG of the given dark/light pixel rows, with every scanline
    encoded using one filter type."""
    height, width = len(dark), len(dark[0])
    raw, prior = b"", bytes(3 * width)
    for row in dark:
        line = b"".join(b"\x10\x20\x30" if d else b"\xf0\xe0\xd0" for d in row)
        out = bytearray()
        for i, x in enumerate(line):
            a = line[i - 3] if i >= 3 else 0
            b, c = prior[i], prior[i - 3] if i >= 3 else 0
            p = a + b - c
            paeth = min((abs(p - a), 0, a), (abs(p - b), 1, b), (abs(p - c), 2, c))[2]
            out.append((x - (0, a, b, (a + b) // 2, paeth)[filter_type]) & 255)
        raw += bytes([filter_type]) + out
        prior = line
    return (_SIGNATURE
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def carved(rows, cols, keep):
    return {(r, c) for r in range(rows) for c in range(cols) if not keep(r, c)}


# Shapes that stress reading the picture back: a blocked corner cell, a maze
# that never touches the edge of the picture, a hole, and separate prongs.
MAPS = {
    "corner": (6, 7, carved(6, 7, lambda r, c: r + c > 2), (0, 3), (5, 6)),
    "island": (7, 8, carved(7, 8, lambda r, c: 1 <= r <= 5 and 1 <= c <= 6), (1, 1), (5, 6)),
    "ring": (7, 7, {(r, c) for r in range(2, 5) for c in range(2, 5)}, (0, 0), (6, 6)),
    "prongs": (6, 9, {(r, c) for r in range(0, 4) for c in (1, 3, 5, 7)}, (0, 0), (0, 8)),
    "full": (5, 6, set(), (0, 0), (4, 5)),
}


class MapRenderTest(unittest.TestCase):
    def test_png_round_trip(self):
        for name, (rows, cols, blocked, start, end) in MAPS.items():
            maze = encode_map(b"m", rows, cols, blocked, start, end)
            for cell, wall in [(12, 4), (1, 1), (5, 2), (3, 7)]:
                back = from_png(to_png(maze, cell, wall))
                self.assertEqual((back.rows, back.cols, back.blocked), (rows, cols, frozenset(blocked)), name)
                self.assertEqual((back.down, back.right, back.doors), (maze.down, maze.right, ()), name)
                self.assertEqual(decode(back), b"m", name)

    def test_enlarged_png(self):
        rows, cols, blocked, start, end = MAPS["island"]
        maze = encode_map(b"m", rows, cols, blocked, start, end)
        dark = _dark_pixels(to_png(maze, cell=6, wall=2))
        enlarged = [bytes(d for d in row for _ in range(3)) for row in dark for _ in range(3)]
        self.assertEqual(decode(from_png(rgb_png(enlarged, 4))), b"m")

    def test_marks_read_as_paper(self):
        rows, cols, blocked, start, end = MAPS["full"]
        maze = encode_map(b"", rows, cols, blocked, start, end)
        unmarked = Maze(rows, cols, maze.down, maze.right)
        self.assertEqual(_dark_pixels(to_png(maze)), _dark_pixels(to_png(unmarked)))

    def test_text_round_trip(self):
        for name, (rows, cols, blocked, start, end) in MAPS.items():
            maze = encode_map(b"m", rows, cols, blocked, start, end)
            text = to_text(maze)
            self.assertEqual(text.count("###"), len(blocked), name)
            self.assertEqual(from_text(text), maze, name)

    def test_openings_and_blocked_cells_do_not_mix(self):
        with self.assertRaisesRegex(ValueError, "two openings"):
            from_text("+   +---+\n|   |###|\n+   +---+\n")


class TextTest(unittest.TestCase):
    def test_round_trip(self):
        for rows, cols in [(1, 1), (1, 6), (6, 1), (7, 9)]:
            maze = encode(b"", rows, cols)
            self.assertEqual(from_text(to_text(maze)), maze)

    def test_blank_corridor_line(self):
        # One row, open from the left edge to the right edge.
        maze = Maze(1, 3, [], [[True, True]], (6, 7))
        self.assertEqual(to_text(maze).splitlines()[1], "")
        self.assertEqual(from_text(to_text(maze)), maze)

    def test_needs_two_doors(self):
        with self.assertRaisesRegex(ValueError, "two openings"):
            from_text("+   +\n|   |\n+---+\n")


class PngTest(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(3)
        for rows, cols in [(1, 1), (1, 6), (6, 1), (9, 7)]:
            maze = encode(b"", rows, cols, seed=rng.randbytes(4))
            for cell, wall in [(12, 4), (1, 1), (5, 2), (3, 7)]:
                self.assertEqual(from_png(to_png(maze, cell, wall)), maze)

    def test_rgb_enlarged_and_filtered(self):
        maze = encode(b"png", 6, 8)
        dark = _dark_pixels(to_png(maze, cell=3, wall=1))
        enlarged = [bytes(d for d in row for _ in range(2)) for row in dark for _ in range(2)]
        for filter_type in range(5):
            self.assertEqual(from_png(rgb_png(enlarged, filter_type)), maze)

    def test_one_bit_per_pixel(self):
        maze = encode(b"1bit", 6, 8)
        dark = _dark_pixels(to_png(maze, cell=3, wall=2))
        width = len(dark[0])
        raw = b"".join(
            b"\0" + bytes(sum((not d) << 7 - i for i, d in enumerate(row[x:x + 8]))
                          for x in range(0, width, 8))
            for row in dark)
        png = (_SIGNATURE
               + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(dark), 1, 0, 0, 0, 0))
               + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))
        self.assertEqual(from_png(png), maze)

    def test_not_a_maze(self):
        with self.assertRaises(ValueError):
            from_png(b"not a png")
        with self.assertRaises(ValueError):
            from_png(rgb_png([bytes(8)] * 8, 0))


if __name__ == "__main__":
    unittest.main()
