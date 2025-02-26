# ruff: noqa

from typing import NamedTuple
from argparse import ArgumentParser

from .configurations import stage_widget, light_widget


class Options(NamedTuple):
    stage: bool
    light: bool


def main() -> None:
    """Main function to run the script."""

    parser = ArgumentParser(description="CLI for redsun-mimir examples")

    # Create a mutually exclusive group
    parser.add_argument(
        "-s", "--stage", action="store_true", help="launch the StageWidget example"
    )
    parser.add_argument(
        "-l", "--light", action="store_true", help="launch the LightWidget example"
    )

    args = Options(**vars(parser.parse_args()))

    if args.stage:
        stage_widget()
    elif args.light:
        light_widget()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
