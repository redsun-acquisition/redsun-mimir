from argparse import ArgumentParser, Namespace

import redsun_mimir.configurations as configurations


class Options(Namespace):
    """Parser options."""

    command: str = ""


def main() -> None:
    """Run main function to run the script."""
    parser = ArgumentParser(description="CLI for redsun-mimir examples")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("sim", help="Run the full simulation example")
    subparsers.add_parser(
        "uc2", help="Run UC2 microscope application with pre-shipped configuration."
    )
    subparsers.add_parser("motor", help="Run the mock motor example")
    subparsers.add_parser("light", help="Run the mock light example")
    subparsers.add_parser(
        "acquisition",
        help="Run the example acquisition container",
    )

    options = parser.parse_args(namespace=Options())
    if options.command == "sim":
        configurations.run_simulation_container()
    elif options.command == "uc2":
        configurations.run_uc2_container()
    elif options.command == "motor":
        configurations.run_stage_container()
    elif options.command == "light":
        configurations.run_light_container()
    elif options.command == "acquisition":
        configurations.run_acquisition_container()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
