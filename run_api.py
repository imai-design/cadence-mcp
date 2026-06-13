#!/usr/bin/env python3
"""Start the Cadence AI-facing HTTP API."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cadence.api import serve  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Cadence AI HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", help="API token. Defaults to CADENCE_API_TOKEN.")
    parser.add_argument("--base-url", help="Public URL to advertise in OpenAPI.")
    args = parser.parse_args()
    serve(args.host, args.port, args.token, args.base_url)


if __name__ == "__main__":
    main()
