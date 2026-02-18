from argparse import ArgumentParser, Namespace


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
    subparsers.add_parser(
        "acquisition-detector-uc2",
        help="Run the acquisition widget with background detector controller and UC2 devices",
    )

    options = parser.parse_args(namespace=Options())
    if options.command == "stage":
        from redsun_mimir.configurations._motor import stage_widget
        stage_widget()
    elif options.command == "stage-uc2":
        from redsun_mimir.configurations._motor_uc2 import stage_widget_uc2
        stage_widget_uc2()
    elif options.command == "light":
        from redsun_mimir.configurations._light import light_widget
        light_widget()
    elif options.command == "light-uc2":
        from redsun_mimir.configurations._light_uc2 import light_widget_uc2
        light_widget_uc2()
    elif options.command == "detector":
        from redsun_mimir.configurations._detector import detector_widget
        detector_widget()
    elif options.command == "detector-uc2":
        from redsun_mimir.configurations._detector_uc2 import detector_widget_uc2
        detector_widget_uc2()
    elif options.command == "acquisition":
        from redsun_mimir.configurations._acquisition import acquisition_widget
        acquisition_widget()
    elif options.command == "acquisition-uc2":
        from redsun_mimir.configurations._acquisition_uc2 import acquisition_widget_uc2
        acquisition_widget_uc2()
    elif options.command == "acquisition-detector":
        from redsun_mimir.configurations._acquisition_detector import acquisition_detector_widget
        acquisition_detector_widget()
    elif options.command == "acquisition-detector-uc2":
        from redsun_mimir.configurations._acquisition_detector_uc2 import acquisition_detector_widget_uc2
        acquisition_detector_widget_uc2()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
