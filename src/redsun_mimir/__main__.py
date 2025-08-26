from argparse import ArgumentParser, Namespace

import redsun_mimir.configurations as configurations


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
    subparsers.add_parser("detector", help="Run the detector widget")
    subparsers.add_parser("detector-uc2", help="Run the detector widget with UC2")
    subparsers.add_parser("acquisition", help="Run the acquisition widget")
    subparsers.add_parser("acquisition-uc2", help="Run the acquisition widget with UC2")
    subparsers.add_parser(
        "acquisition-detector",
        help="Run the acquisition widget with background detector controller",
    )

    options = parser.parse_args(namespace=Options())
    if options.command == "stage":
        configurations.stage_widget()
    elif options.command == "stage-uc2":
        configurations.stage_widget_uc2()
    elif options.command == "light":
        configurations.light_widget()
    elif options.command == "light-uc2":
        configurations.light_widget_uc2()
    elif options.command == "detector":
        configurations.detector_widget()
    elif options.command == "detector-uc2":
        configurations.detector_widget_uc2()
    elif options.command == "acquisition":
        configurations.acquisition_widget()
    elif options.command == "acquisition-uc2":
        configurations.acquisition_widget_uc2()
    elif options.command == "acquisition-detector":
        configurations.acquisition_detector_widget()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
