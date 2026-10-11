import random
import unittest

from mazestego import capacity, decode, encode, encode_map, estimate_capacity


def key(maze):
    return (tuple(map(tuple, maze.down)), tuple(map(tuple, maze.right)), maze.doors)


class RoundTripTest(unittest.TestCase):
    def test_messages(self):
        rng = random.Random(2)
        for rows, cols in [(8, 8), (5, 12), (12, 5)]:
            held = capacity(rows, cols).bytes
            messages = [b"", b"\0", b"\0\0\0", b"hello", b"\xff" * held,
                        rng.randbytes(held), "çà et là".encode()]
            for message in messages:
                self.assertEqual(decode(encode(message, rows, cols)), message)

    def test_every_state_holds_a_different_message(self):
        # 2x2: 4 trees x 28 door pairs = 112 states = the empty message plus
        # the 111 single bytes 0..110.
        messages = [b""] + [bytes([b]) for b in range(111)]
        self.assertEqual(capacity(2, 2).states, len(messages))
        mazes = {key(encode(message, 2, 2)) for message in messages}
        self.assertEqual(len(mazes), len(messages))
        with self.assertRaises(ValueError):
            encode(bytes([111]), 2, 2)

    def test_message_too_long(self):
        held = capacity(6, 6).bytes
        with self.assertRaisesRegex(ValueError, f"holds {held} bytes"):
            encode(b"\xff" * (held + 1), 6, 6)

    def test_seed(self):
        plain = encode(b"secret", 8, 8)
        seeded = encode(b"secret", 8, 8, seed=b"k")
        self.assertNotEqual(key(plain), key(seeded))
        self.assertEqual(decode(seeded, seed=b"k"), b"secret")
        self.assertNotEqual(decode(seeded), b"secret")


RING = {(r, c) for r in range(3, 6) for c in range(3, 8)}   # a 9x11 grid with a hole


class MapTest(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(6)
        held = capacity(9, 11, RING).bytes
        for message in [b"", b"\0\0", b"map", b"\xff" * held, rng.randbytes(held)]:
            maze = encode_map(message, 9, 11, RING, (0, 0), (8, 10), seed=b"s")
            self.assertTrue(maze.is_map)
            self.assertEqual((maze.start, maze.end), ((0, 0), (8, 10)))
            self.assertEqual(decode(maze, seed=b"s"), message)

    def test_every_state_holds_a_different_message(self):
        # A 2x3 block has 15 mazes: the empty message and the bytes 0..13.
        messages = [b""] + [bytes([b]) for b in range(14)]
        mazes = {key(encode_map(m, 2, 3, (), (0, 0), (1, 2))) for m in messages}
        self.assertEqual(len(mazes), 15)
        with self.assertRaises(ValueError):
            encode_map(bytes([14]), 2, 3, (), (0, 0), (1, 2))

    def test_shape_changes_the_maze_not_just_the_cells(self):
        # The same message in a full grid, as a plain maze and as a map.
        self.assertEqual(decode(encode_map(b"same", 8, 8, (), (0, 0), (7, 7))), b"same")
        self.assertEqual(decode(encode(b"same", 8, 8)), b"same")

    def test_estimate_matches_exact_capacity(self):
        exact = capacity(9, 11, RING)
        bits, held = estimate_capacity(9, 11, RING)
        self.assertAlmostEqual(bits, exact.bits, places=9)
        self.assertEqual(held, exact.bytes)

    def test_bad_requests(self):
        cases = [
            ("start must be on a cell", dict(blocked=RING, start=(4, 4), end=(8, 10))),
            ("end must be on a cell", dict(blocked=RING, start=(0, 0), end=(9, 0))),
            ("different cells", dict(blocked=RING, start=(0, 0), end=(0, 0))),
            ("connected", dict(blocked={(r, 5) for r in range(9)}, start=(0, 0), end=(8, 10))),
            ("does not fit", dict(blocked=RING, start=(0, 0), end=(8, 10), message=b"x" * 99)),
        ]
        for expected, case in cases:
            message = case.pop("message", b"")
            with self.assertRaisesRegex(ValueError, expected):
                encode_map(message, 9, 11, **case)

    def test_shape_with_one_maze_is_refused(self):
        snake = {(1, c) for c in range(4)} | {(3, c) for c in range(1, 5)}
        with self.assertRaisesRegex(ValueError, "only one maze"):
            encode_map(b"", 5, 5, snake, (0, 0), (4, 4))


class CapacityTest(unittest.TestCase):
    def test_bits_and_bytes(self):
        cap = capacity(8, 8)
        # log2(126231322912498539682594816 trees) + log2(C(32, 2) door pairs)
        self.assertAlmostEqual(cap.bits, 86.706 + 8.954, places=2)
        self.assertEqual(cap.bytes, 11)


if __name__ == "__main__":
    unittest.main()
