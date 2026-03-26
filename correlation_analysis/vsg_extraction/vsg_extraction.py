"""VSG Extraction script – invoked by Abaqus Python.

Usage (via Abaqus):
    abaqus [--version=<ver>] python vsg_extraction.py <input_file>
           [--component-index=<n>] [--radius-tolerance=<n>]
           [--intervals=<n>] [--angle-step=<n>] [--print-vsg]

The script is designed to run inside the Abaqus Python interpreter,
so it intentionally avoids third-party imports that are unavailable there.
"""
from __future__ import annotations

import argparse
import os
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract VSG data from an Abaqus input file."
    )
    parser.add_argument("input_file", help="Path to the input .txt file")
    parser.add_argument(
        "--component-index",
        type=int,
        default=1,
        metavar="N",
        help="Component index (default: 1)",
    )
    parser.add_argument(
        "--radius-tolerance",
        type=float,
        default=3.0,
        metavar="R",
        help="Radius tolerance (default: 3)",
    )
    parser.add_argument(
        "--intervals",
        type=int,
        default=100,
        metavar="N",
        help="Number of intervals (default: 100)",
    )
    parser.add_argument(
        "--angle-step",
        type=float,
        default=10.0,
        metavar="DEG",
        help="Angle step in degrees (default: 10)",
    )
    parser.add_argument(
        "--print-vsg",
        action="store_true",
        help="Print VSG extraction details to stdout",
    )
    return parser.parse_args(argv)


def run_extraction(
    input_file: str,
    component_index: int,
    radius_tolerance: float,
    intervals: int,
    angle_step: float,
    print_vsg: bool,
) -> None:
    """Main extraction logic – replace the body with the real Abaqus calls."""
    if not os.path.isfile(input_file):
        print(f"ERROR: input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Starting VSG extraction")
    print(f"  Input file       : {input_file}")
    print(f"  Component index  : {component_index}")
    print(f"  Radius tolerance : {radius_tolerance}")
    print(f"  Intervals        : {intervals}")
    print(f"  Angle step       : {angle_step}")
    print(f"  Print VSG        : {print_vsg}")

    # TODO: insert actual Abaqus / VSG extraction logic here
    # e.g.:
    #   from odbAccess import openOdb
    #   ...

    print("VSG extraction completed successfully.")


def main() -> None:
    args = parse_args()
    run_extraction(
        input_file=args.input_file,
        component_index=args.component_index,
        radius_tolerance=args.radius_tolerance,
        intervals=args.intervals,
        angle_step=args.angle_step,
        print_vsg=args.print_vsg,
    )


if __name__ == "__main__":
    main()
