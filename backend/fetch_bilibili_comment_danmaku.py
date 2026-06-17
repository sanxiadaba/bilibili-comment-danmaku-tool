import sys

from app_cli import main


if __name__ == "__main__":
    raise SystemExit(main(["fetch-video", *sys.argv[1:]]))
