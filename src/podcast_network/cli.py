from __future__ import annotations

import argparse
import os


def database_graph():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "podcast_network.web.settings")
    import django

    django.setup()

    from podcast_network.web.explorer.services import database_six_degrees_graph

    return database_six_degrees_graph()


def main() -> None:
    parser = argparse.ArgumentParser(prog="podcast-network")
    subparsers = parser.add_subparsers(dest="command", required=True)

    path_parser = subparsers.add_parser("path", help="Find the shortest podcast-network path.")
    path_parser.add_argument("source")
    path_parser.add_argument("target")

    args = parser.parse_args()
    if args.command == "path":
        result = database_graph().explain(args.source, args.target)
        print(result.message)
        if result.found:
            print(f"Length: {result.length}")


if __name__ == "__main__":
    main()
