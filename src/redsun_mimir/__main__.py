from argparse import ArgumentParser, Namespace

from redsun_mimir import configurations


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

    options = parser.parse_args(namespace=Options())
    if options.command == "sim":
        configurations.run_simulation_container()
    elif options.command == "uc2":
        configurations.run_uc2_container()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
