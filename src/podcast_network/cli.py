from __future__ import annotations

import argparse

from podcast_network.graph import SixDegreesGraph


def main() -> None:
    parser = argparse.ArgumentParser(prog="podcast-network")
    subparsers = parser.add_subparsers(dest="command", required=True)

    path_parser = subparsers.add_parser("path", help="Find the shortest podcast-network path.")
    path_parser.add_argument("source")
    path_parser.add_argument("target")

    args = parser.parse_args()
    if args.command == "path":
        graph = SixDegreesGraph.from_legacy_dir()
        result = graph.explain(args.source, args.target)
        print(result.message)
        if result.found:
            print(f"Length: {result.length}")


if __name__ == "__main__":
    main()

