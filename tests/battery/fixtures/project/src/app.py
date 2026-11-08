import sys

from util import greet


def main() -> int:
    # TODO: parse arguments
    print(greet(sys.argv[1] if len(sys.argv) > 1 else "world"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
