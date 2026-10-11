import math
import random
import struct
import unittest
import zlib

from mazestego import (
    Board, CircleMaze, Maze, decode, encode, encode_board, encode_circle,
    estimate_board_capacity, from_png, to_png, to_text,
)
from mazestego.board import Layout, area_text, default_places, parse_area, ring, straight
from mazestego.render import _PALETTE, _SIGNATURE, _chunk

MIXES = [
    [straight(4, 5), ring(3)],
    [ring(3), straight(3, 7)],
    [straight(6, 4), ring(4), straight(2, 9), ring(3)],
    [straight(5, 5), straight(3, 6)],
    [straight(3, 3), straight(5, 5), straight(2, 6)],
]

# A 6x8 area with a circle of four rings below it and a 4x4 area to the
# right of the circle: the path goes down, then across.
BENT = [straight(6, 8), ring(4), straight(4, 4)]
BENT_PLACES = [(2, 0), (0, 18), (26, 24)]


class TextTest(unittest.TestCase):
    def test_area_text(self):
        for text in ("8x12", "circle6"):
            self.assertEqual(area_text(parse_area(text)), text)
        for text in ("8", "round6", "axb", "circle"):
            with self.assertRaisesRegex(ValueError, "not an area"):
                parse_area(text)


class LayoutTest(unittest.TestCase):
    def test_straight_area_grows_across_to_a_circle(self):
        layout = Layout([straight(8, 10), ring(6)], [(0, 6), (26, 0)])
        joint, = layout.joints
        self.assertEqual((joint.owner, joint.other, joint.side, joint.lanes), (0, 1, "right", 8))
        # Eight neighbouring stretches of the circle's wall, facing left.
        self.assertEqual(len(set(joint.landing)), 8)
        self.assertTrue(all(12 <= index < 36 for index in joint.landing))
        # The area's grid is its own cells plus the lanes, eight rows deep.
        top, left, rows, cols, blocked = layout.frames[0]
        self.assertEqual((top, left, rows, cols, len(blocked)), (0, 0, 8, 10 + joint.deep, 0))
        # Each line between lanes starts on the area and ends on the circle.
        for lane, curve in enumerate(joint.curves):
            self.assertEqual(curve[0], (10.0, 3.0 + lane))
            self.assertAlmostEqual(math.hypot(curve[3][0] - 20, curve[3][1] - 7), 7)

    def test_shorter_end_grows_onto_longer_side(self):
        layout = Layout([straight(8, 4), straight(3, 5)], [(0, 0), (14, 4)])
        joint, = layout.joints
        self.assertEqual((joint.owner, joint.other, joint.side, joint.lanes), (1, 0, "left", 3))
        self.assertEqual(len(joint.landing), 3)
        self.assertTrue(all(layout.shapes[0].side_of(index) == "right" for index in joint.landing))

    def test_two_sides_cut_the_corner_of_the_grid(self):
        # Joined below and to the right: lanes on two sides, nothing in the corner.
        areas = [ring(3), straight(4, 4), ring(3)]
        layout = Layout(areas, [(0, 12), (20, 14), (22, 30)])
        top, left, rows, cols, blocked = layout.frames[1]
        self.assertEqual(set(layout.grown[1]), {"left", "bottom"})
        self.assertEqual(len(blocked), layout.grown[1]["left"].deep * layout.grown[1]["bottom"].deep)
        self.assertEqual(layout.trees[1].cells, rows * cols - len(blocked))

    def test_start_and_end_avoid_the_joints(self):
        layout = Layout(BENT, BENT_PLACES)
        self.assertIn(layout.start, layout.free_gaps(0))
        self.assertIn(layout.end, layout.free_gaps(2))
        self.assertNotIn(layout.shapes[0].side_of(layout.start), layout.grown[0])
        with self.assertRaisesRegex(ValueError, "start must be on a stretch of outer wall"):
            Layout(BENT, BENT_PLACES, start=8 + 3)      # the bottom wall, where it grows

    def problem(self, areas, places):
        with self.assertRaises(ValueError) as caught:
            Layout(areas, places)
        return str(caught.exception)

    def test_problems_are_named(self):
        self.assertIn("areas 1 and 2 overlap", self.problem(BENT, [(2, 0), (0, 6), (26, 24)]))
        self.assertIn("areas 1 and 2 are both circles", self.problem([ring(3), ring(3)], [(0, 0), (20, 0)]))
        self.assertIn("too small", self.problem([straight(9, 4), ring(2)], [(0, 0), (12, 4)]))
        self.assertIn("every area needs a place", self.problem(BENT, BENT_PLACES[:2]))
        self.assertIn("at least 2 areas", self.problem([straight(5, 5)], [(0, 0)]))
        # A small area with both its bigger neighbours to its left.
        wedged = [straight(4, 4), straight(2, 2), straight(4, 4)]
        self.assertIn("area 2 is joined to both its neighbours on the same side",
                      self.problem(wedged, [(0, 0), (12, 6), (0, 10)]))


class CodecTest(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(12)
        for areas in MIXES:
            held = estimate_board_capacity(areas)[1]
            for message in [b"", b"\0", b"\xff" * held, rng.randbytes(held)]:
                board = encode_board(message, areas, seed=b"s")
                self.assertEqual(decode(board, seed=b"s"), message, areas)

    def test_every_state_holds_a_different_message(self):
        # Two cells above each other, twice, two cells apart: the first grows
        # into a 2x3 grid (15 mazes), and the gate can be in either lane.
        areas, places = [straight(2, 1), straight(2, 1)], [(0, 0), (6, 0)]
        layout = Layout(areas, places)
        states = layout.states()
        self.assertEqual(states, 15 * 1 * 2)
        self.assertLess(states, 257)
        messages = [b""] + [bytes([b]) for b in range(states - 1)]
        boards = {repr(encode_board(m, areas, places)) for m in messages}
        self.assertEqual(len(boards), states)
        with self.assertRaises(ValueError):
            encode_board(bytes([states - 1]), areas, places)

    def test_lanes_and_gates_add_to_what_it_holds(self):
        areas = [straight(5, 6), ring(3)]
        bits, _ = estimate_board_capacity(areas)
        apart = math.log2(Layout([straight(5, 6), straight(1, 1)], [(0, 0), (20, 0)]).trees[0].count)
        self.assertGreater(bits, apart + Layout(areas, default_places(areas)).trees[1].estimate_bits())

    def test_where_it_is_placed_matters(self):
        row = encode_board(b"same", BENT)
        bent = encode_board(b"same", BENT, BENT_PLACES)
        self.assertEqual(decode(row), b"same")
        self.assertEqual(decode(bent), b"same")
        self.assertNotEqual(row.places, bent.places)

    def test_chosen_start_and_end(self):
        # Top wall of the first area, column 2; right wall of the last, row 1.
        board = encode_board(b"ends", BENT, BENT_PLACES, start=2, end=12 + 1)
        self.assertEqual((board.start, board.end), (2, 13))
        self.assertEqual(decode(board), b"ends")


class PngTest(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(13)
        for areas in MIXES:
            board = encode_board(rng.randbytes(2), areas)
            for cell, wall in [(12, 4), (9, 3)]:
                self.assertEqual(from_png(to_png(board, cell, wall)), board, (areas, cell, wall))

    def test_hand_placed_round_trip(self):
        board = encode_board(b"bent", BENT, BENT_PLACES, seed=b"k")
        back = from_png(to_png(board))
        self.assertIsInstance(back, Board)
        self.assertEqual(back, board)
        self.assertEqual(decode(back, seed=b"k"), b"bent")

    def test_layout_survives_resaving_as_rgb(self):
        board = encode_board(b"rgb", [straight(4, 5), ring(3)])
        png = to_png(board)
        width, height = struct.unpack(">II", png[16:24])
        raw = zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
        rows = [raw[y * (width + 1) + 1:(y + 1) * (width + 1)] for y in range(height)]
        rgb = b"".join(b"\0" + b"".join(_PALETTE[3 * v:3 * v + 3] for v in row) for row in rows)
        resaved = (_SIGNATURE
                   + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                   + _chunk(b"IDAT", zlib.compress(rgb)) + _chunk(b"IEND", b""))
        self.assertEqual(decode(from_png(resaved)), b"rgb")

    def test_too_small_to_draw(self):
        with self.assertRaisesRegex(ValueError, "larger cell or wall"):
            to_png(encode_board(b"", [straight(4, 5), ring(3)]), cell=2, wall=1)

    def test_no_text_form(self):
        with self.assertRaisesRegex(ValueError, "PNG"):
            to_text(encode_board(b"", [straight(2, 2), straight(2, 2)]))

    def test_single_mazes_still_read_as_themselves(self):
        self.assertIsInstance(from_png(to_png(encode(b"", 6, 6))), Maze)
        self.assertIsInstance(from_png(to_png(encode_circle(b"", 4))), CircleMaze)

    def test_plain_maze_with_a_clear_corridor(self):
        # A straight corridor from a door in the top wall to one in the bottom.
        down = [[False, True, False] for _ in range(2)]
        maze = Maze(3, 3, down, [[True, True] for _ in range(3)], (1, 4))
        self.assertEqual(from_png(to_png(maze)), maze)


if __name__ == "__main__":
    unittest.main()
