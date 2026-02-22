from argparse import ArgumentParser, Namespace

import redsun_mimir.configurations as configurations


class Options(Namespace):
    """Parser options."""

    command: str = ""


def main() -> None:
    """Run main function to run the script."""
    parser = ArgumentParser(description="CLI for redsun-mimir examples")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("motor", help="Run the mock motor example")
    subparsers.add_parser("motor-uc2", help="Run the UC2 motor example")
    subparsers.add_parser("light", help="Run the mock light example")
    subparsers.add_parser("light-uc2", help="Run the UC2 light example")
    subparsers.add_parser(
        "acquisition-uc2",
        help="Run the UC2 example acquisition container",
    )

    options = parser.parse_args(namespace=Options())
    if options.command == "motor":
        configurations.run_stage_container()
    elif options.command == "motor-uc2":
        configurations.run_youseetoo_motor_container()
    elif options.command == "light":
        configurations.run_light_container()
    elif options.command == "light-uc2":
        configurations.run_youseetoo_light_container()
    elif options.command == "acquisition-uc2":
        configurations.run_youseetoo_acquisition_container()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
