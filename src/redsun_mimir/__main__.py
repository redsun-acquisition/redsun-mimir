from argparse import ArgumentParser, Namespace

from redsun_mimir.configurations import (
    acquisition_widget,
    image_widget,
    image_widget_uc2,
    light_widget,
    light_widget_uc2,
    stage_widget,
    stage_widget_uc2,
)


class Options(Namespace):
    """Parser options."""

    command: str = ""


def main() -> None:
    """Run main function to run the script."""
    parser = ArgumentParser(description="CLI for redsun-mimir examples")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("stage", help="Run the stage widget")
    subparsers.add_parser("stage-uc2", help="Run the stage widget with UC2")
    subparsers.add_parser("light", help="Run the light widget")
    subparsers.add_parser("light-uc2", help="Run the light widget with UC2")
    subparsers.add_parser("image", help="Run the image widget")
    subparsers.add_parser("acquisition", help="Run the acquisition widget")
    subparsers.add_parser("image-uc2", help="Run the image widget with UC2")

    options = parser.parse_args(namespace=Options())
    if options.command == "stage":
        stage_widget()
    elif options.command == "stage-uc2":
        stage_widget_uc2()
    elif options.command == "light":
        light_widget()
    elif options.command == "light-uc2":
        light_widget_uc2()
    elif options.command == "image":
        image_widget()
    elif options.command == "image-uc2":
        image_widget_uc2()
    elif options.command == "acquisition":
        acquisition_widget()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
