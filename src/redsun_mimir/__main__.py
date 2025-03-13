# ruff: noqa

from argparse import ArgumentParser, Namespace
from typing import Any

from .configurations import stage_widget, light_widget


class Options(Namespace):
    command: str = ""


def main() -> None:
    """Main function to run the script."""

    parser = ArgumentParser(description="CLI for redsun-mimir examples")
    subparsers = parser.add_subparsers(dest="command")
    stage_parser = subparsers.add_parser(
        "stage", help='Run the stage widget (type "stage --help" for more options)'
    )
    subparsers.add_parser("light", help="Run the light widget")

    options = parser.parse_args(namespace=Options())
    if options.command == "stage":
        stage_widget()
    elif options.command == "light":
        light_widget()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
