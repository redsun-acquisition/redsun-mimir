from argparse import ArgumentParser, Namespace

from redsun_mimir.configurations import (
    acquisition_widget,
    detector_widget,
    image_widget,
    light_widget,
    light_widget_uc2,
    stage_widget,
)


class Options(Namespace):
    """Parser options."""

    command: str = ""


def main() -> None:
    """Run main function to run the script."""
    parser = ArgumentParser(description="CLI for redsun-mimir examples")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("stage", help="Run the stage widget")
    subparsers.add_parser("light", help="Run the light widget")
    subparsers.add_parser("light-uc2", help="Run the light widget with UC2")
    subparsers.add_parser("detector", help="Run the detector widget")
    subparsers.add_parser("acquisition", help="Run the acquisition widget")
    subparsers.add_parser("image", help="Run the image widget")

    options = parser.parse_args(namespace=Options())
    if options.command == "stage":
        stage_widget()
    elif options.command == "light":
        light_widget()
    elif options.command == "light-uc2":
        light_widget_uc2()
    elif options.command == "detector":
        detector_widget()
    elif options.command == "acquisition":
        acquisition_widget()
    elif options.command == "image":
        image_widget()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
