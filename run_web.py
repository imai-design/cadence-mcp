#!/usr/bin/env python3
"""Start the Cadence Now local PWA."""
import argparse
import pathlib
import sys
import threading
import webbrowser

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cadence.web import serve  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Cadence Now local PWA")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if not args.no_open:
        threading.Timer(0.5, webbrowser.open, args=(f"http://{args.host}:{args.port}",)).start()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
