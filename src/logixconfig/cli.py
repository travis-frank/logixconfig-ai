"""Command line interface: logixconfig generate equipment.csv -o out --controller-name Skid01"""

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

from logixconfig.io import read_equipment, write_docs, write_tags_csv
from logixconfig.io_list import io_rows, write_io_list
from logixconfig.l5x import (
    DEFAULT_BUS_SIZE,
    DEFAULT_MAJOR_REV,
    DEFAULT_MINOR_REV,
    build_l5x,
    default_software_revision,
)
from logixconfig.models import Equipment, Tag
from logixconfig.templates import tags_for
from logixconfig.validator import Issue, has_errors, name_issues, validate


class L5xProfile(NamedTuple):
    software_revision: str = default_software_revision(DEFAULT_MAJOR_REV)
    major_rev: int = DEFAULT_MAJOR_REV
    minor_rev: int = DEFAULT_MINOR_REV
    bus_size: int = DEFAULT_BUS_SIZE
    include_descriptions: bool = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="logixconfig", description="Generate Logix tags and draft docs.")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Generate tags, docs, I/O list, and a starter L5X from a CSV")
    generate.add_argument("equipment_csv", type=Path, help="CSV with columns name,type,description")
    generate.add_argument("-o", "--output", type=Path, required=True, help="Output directory")
    generate.add_argument("--controller-name", required=True, help="Controller name for the L5X file")
    generate.add_argument("--major-rev", type=int, default=DEFAULT_MAJOR_REV, help="Controller firmware major revision")
    generate.add_argument("--minor-rev", type=int, default=DEFAULT_MINOR_REV, help="Controller firmware minor revision")
    generate.add_argument(
        "--software-revision",
        help="L5X SoftwareRevision; its major part must equal --major-rev (default: 24.02 for v24, else <major>.00)",
    )
    generate.add_argument("--bus-size", type=int, default=DEFAULT_BUS_SIZE, help="Number of slots in the local chassis")
    generate.add_argument("--no-descriptions", action="store_true", help="Leave tag descriptions out of the L5X")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = L5xProfile(
        software_revision=args.software_revision or default_software_revision(args.major_rev),
        major_rev=args.major_rev,
        minor_rev=args.minor_rev,
        bus_size=args.bus_size,
        include_descriptions=not args.no_descriptions,
    )
    return generate(args.equipment_csv, args.output, args.controller_name, profile)


def generate(csv_path: Path, output: Path, controller_name: str, profile: L5xProfile | None = None) -> int:
    profile = profile or L5xProfile()
    try:
        equipment = read_equipment(csv_path)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    tags = [tag for item in equipment for tag in tags_for(item)]
    issues = name_issues(controller_name, label="Controller name") + validate(tags)
    print_issues(issues)
    if has_errors(issues):
        print("error: validation failed, no files written", file=sys.stderr)
        return 1

    try:
        l5x = build_l5x(
            tags,
            controller_name,
            profile.software_revision,
            profile.major_rev,
            profile.minor_rev,
            profile.bus_size,
            include_descriptions=profile.include_descriptions,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    write_outputs(output, controller_name, equipment, tags, l5x)
    print(f"Wrote {len(tags)} tags for {len(equipment)} equipment items to {output}")
    return 0


def write_outputs(output: Path, controller_name: str, equipment: list[Equipment], tags: list[Tag], l5x: bytes) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_tags_csv(tags, output / "tags.csv")
    write_docs(equipment, tags, output / "docs.md")
    write_io_list(io_rows(tags), output / "io_list.csv")
    (output / f"{controller_name}.L5X").write_bytes(l5x)


def print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        print(f"{issue.severity.value}: [{issue.rule}] {issue.message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
