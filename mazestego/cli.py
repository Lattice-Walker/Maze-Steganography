"""Command line: ``python -m mazestego {encode,circle,mixed,decode,capacity,serve}``."""

import argparse
import sys

from . import codec, render
from .board import parse_area


def _progress():
    """A progress callback that draws on stderr, or None when it is not a terminal."""
    if not sys.stderr.isatty():
        return None

    def show(done, total):
        end = "\n" if done == total else ""
        print(f"\r  working... {100 * done // total:3d}%", end=end, file=sys.stderr, flush=True)

    return show


def _encode(args):
    message = (sys.stdin.buffer.read() if args.message is None
               else args.message.encode())
    maze = codec.encode(message, args.rows, args.cols, args.seed.encode(), _progress())
    if args.output == "-":
        sys.stdout.write(render.to_text(maze))
    else:
        render.save(maze, args.output, args.cell, args.wall)
    held = codec.capacity(args.rows, args.cols).bytes
    print(f"{args.rows}x{args.cols} maze, {len(message)} of {held} bytes used"
          + ("" if args.output == "-" else f" -> {args.output}"), file=sys.stderr)


def _circle(args):
    message = (sys.stdin.buffer.read() if args.message is None
               else args.message.encode())
    maze = codec.encode_circle(message, args.rings, args.seed.encode(), _progress())
    render.save(maze, args.output, args.cell, args.wall)
    held = codec.estimate_circle_capacity(args.rings)[1]
    print(f"circle maze of {args.rings} rings, {len(message)} of {held} bytes used"
          f" -> {args.output}", file=sys.stderr)


def _mixed(args):
    message = (sys.stdin.buffer.read() if args.message is None
               else args.message.encode())
    areas = [parse_area(text) for text in args.areas]
    maze = codec.encode_board(message, areas, seed=args.seed.encode(), progress=_progress())
    render.save(maze, args.output, args.cell, args.wall)
    held = codec.estimate_board_capacity(areas)[1]
    print(f"mixed map of {len(areas)} areas, {len(message)} of {held} bytes used"
          f" -> {args.output}", file=sys.stderr)


def _decode(args):
    maze = render.load(args.file)
    message = codec.decode(maze, args.seed.encode(), _progress())
    sys.stdout.buffer.write(message)
    if sys.stdout.isatty():
        print()


def _capacity(args):
    if args.areas:
        bits, held = codec.estimate_board_capacity([parse_area(text) for text in args.areas])
        print(f"mixed map of {len(args.areas)} areas: {bits:.1f} bits, "
              f"any message up to {held} bytes")
    elif args.rings is not None:
        bits, held = codec.estimate_circle_capacity(args.rings)
        print(f"circle maze of {args.rings} rings: {bits:.1f} bits, "
              f"any message up to {held} bytes")
    elif args.rows is None or args.cols is None:
        raise ValueError("give rows and columns, --rings for a circle maze, "
                         "or --areas for a mixed map")
    else:
        cap = codec.capacity(args.rows, args.cols)
        print(f"{args.rows}x{args.cols} maze: {cap.bits:.1f} bits, "
              f"any message up to {cap.bytes} bytes")


def _serve(args):
    from . import web
    web.serve(args.host, args.port)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mazestego",
        description="Hide a message in the structure of a perfect maze.")
    sub = parser.add_subparsers(dest="command", required=True)
    seed_help = ("changes which maze a message maps to; "
                 "decoding needs the same value (default: empty)")

    p = sub.add_parser("encode", help="draw the maze that holds a message")
    p.add_argument("rows", type=int)
    p.add_argument("cols", type=int)
    p.add_argument("message", nargs="?", help="text to hide (default: read stdin)")
    p.add_argument("-o", "--output", default="maze.png",
                   help="PNG file, .txt file, or - for text on stdout (default: maze.png)")
    p.add_argument("--seed", default="", help=seed_help)
    p.add_argument("--cell", type=int, default=12, help="corridor width in pixels")
    p.add_argument("--wall", type=int, default=4, help="wall thickness in pixels")
    p.set_defaults(run=_encode)

    p = sub.add_parser("circle", help="draw the circle maze that holds a message")
    p.add_argument("rings", type=int, help="rings around the centre cell")
    p.add_argument("message", nargs="?", help="text to hide (default: read stdin)")
    p.add_argument("-o", "--output", default="maze.png", help="PNG file (default: maze.png)")
    p.add_argument("--seed", default="", help=seed_help)
    p.add_argument("--cell", type=int, default=12, help="corridor width in pixels")
    p.add_argument("--wall", type=int, default=4, help="wall thickness in pixels")
    p.set_defaults(run=_circle)

    area_help = "ROWSxCOLS for a straight area or circleRINGS for a circle, e.g. 8x10 circle6"
    p = sub.add_parser("mixed", help="draw the mixed map that holds a message")
    p.add_argument("areas", nargs="+", metavar="AREA",
                   help="the areas in the order the path crosses them, drawn in a row: " + area_help)
    p.add_argument("-m", "--message", help="text to hide (default: read stdin)")
    p.add_argument("-o", "--output", default="maze.png", help="PNG file (default: maze.png)")
    p.add_argument("--seed", default="", help=seed_help)
    p.add_argument("--cell", type=int, default=12, help="corridor width in pixels")
    p.add_argument("--wall", type=int, default=4, help="wall thickness in pixels")
    p.set_defaults(run=_mixed)

    p = sub.add_parser("decode", help="recover the message from a maze")
    p.add_argument("file", help="PNG or text file written by encode")
    p.add_argument("--seed", default="", help=seed_help)
    p.set_defaults(run=_decode)

    p = sub.add_parser("capacity", help="show how much a maze of a given size holds")
    p.add_argument("rows", type=int, nargs="?")
    p.add_argument("cols", type=int, nargs="?")
    p.add_argument("--rings", type=int, help="size of a circle maze instead")
    p.add_argument("--areas", nargs="+", metavar="AREA", help="areas of a mixed map instead: " + area_help)
    p.set_defaults(run=_capacity)

    p = sub.add_parser("serve", help="run the web interface")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(run=_serve)

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except (ValueError, OSError) as error:
        sys.exit(f"mazestego: {error}")
