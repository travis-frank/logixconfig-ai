"""Command line interface.

logixconfig generate equipment.csv -o out --controller-name Skid01
logixconfig describe "A tank feeds two pumps..." -o out --controller-name Skid01
"""

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

from dotenv import find_dotenv, load_dotenv

from logixconfig.graph import PipelineState, Status, run_pipeline
from logixconfig.io import read_equipment, write_docs, write_tags_csv
from logixconfig.io_list import io_rows, write_io_list
from logixconfig.l5x import (
    DEFAULT_BUS_SIZE,
    DEFAULT_MAJOR_REV,
    DEFAULT_MINOR_REV,
    build_l5x,
    default_software_revision,
)
from logixconfig.llm import API_KEY_ENV_VAR, LLM, MODEL_ENV_VAR, LLMError, OpenAILLM
from logixconfig.models import Equipment, Tag
from logixconfig.templates import tags_for
from logixconfig.validator import Issue, has_errors, name_issues, validate

DEFAULT_CONTROLLER_NAME = "Controller1"


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
    generate.add_argument("--controller-name", required=True, help="Controller name for the L5X file")
    add_output_options(generate)

    describe = commands.add_parser("describe", help="Plan equipment from a plain-English description with an LLM")
    describe.add_argument("text", help="Plain-English process description")
    describe.add_argument(
        "--controller-name", default=DEFAULT_CONTROLLER_NAME, help="Controller name for the L5X file"
    )
    add_output_options(describe)
    return parser


def add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--major-rev", type=int, default=DEFAULT_MAJOR_REV, help="Controller firmware major revision")
    parser.add_argument("--minor-rev", type=int, default=DEFAULT_MINOR_REV, help="Controller firmware minor revision")
    parser.add_argument(
        "--software-revision",
        help="L5X SoftwareRevision; its major part must equal --major-rev (default: 24.02 for v24, else <major>.00)",
    )
    parser.add_argument("--bus-size", type=int, default=DEFAULT_BUS_SIZE, help="Number of slots in the local chassis")
    parser.add_argument("--no-descriptions", action="store_true", help="Leave tag descriptions out of the L5X")


def entry() -> None:
    load_dotenv(find_dotenv(usecwd=True), override=False)
    sys.exit(main())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = L5xProfile(
        software_revision=args.software_revision or default_software_revision(args.major_rev),
        major_rev=args.major_rev,
        minor_rev=args.minor_rev,
        bus_size=args.bus_size,
        include_descriptions=not args.no_descriptions,
    )
    if args.command == "describe":
        return describe(args.text, args.output, args.controller_name, profile)
    return generate(args.equipment_csv, args.output, args.controller_name, profile)


def generate(csv_path: Path, output: Path, controller_name: str, profile: L5xProfile | None = None) -> int:
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
    return write_project(output, controller_name, equipment, tags, profile or L5xProfile())


def create_llm() -> LLM:
    return OpenAILLM.from_env()


def describe(text: str, output: Path, controller_name: str, profile: L5xProfile | None = None) -> int:
    controller_issues = name_issues(controller_name, label="Controller name")
    if controller_issues:
        print_issues(controller_issues)
        print("error: validation failed, no files written", file=sys.stderr)
        return 1

    try:
        llm = create_llm()
    except LLMError as error:
        print(f"error: {error}. Set {MODEL_ENV_VAR} and {API_KEY_ENV_VAR} in your environment or .env", file=sys.stderr)
        return 1

    state = run_pipeline(text, llm)
    print_issues(state["issues"])
    if state["status"] is not Status.SUCCEEDED:
        print("error: could not produce a valid equipment list, no files written", file=sys.stderr)
        return 1

    code = write_project(
        output, controller_name, state["equipment"], state["tags"], profile or L5xProfile(), state["narrative"]
    )
    if code == 0:
        print_planner_notes(state)
    return code


def write_project(
    output: Path,
    controller_name: str,
    equipment: list[Equipment],
    tags: list[Tag],
    profile: L5xProfile,
    narrative: str | None = None,
) -> int:
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

    write_outputs(output, controller_name, equipment, tags, l5x, narrative)
    print(f"Wrote {len(tags)} tags for {len(equipment)} equipment items to {output}")
    return 0


def write_outputs(
    output: Path,
    controller_name: str,
    equipment: list[Equipment],
    tags: list[Tag],
    l5x: bytes,
    narrative: str | None = None,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_tags_csv(tags, output / "tags.csv")
    write_docs(equipment, tags, output / "docs.md", narrative)
    write_io_list(io_rows(tags), output / "io_list.csv")
    (output / f"{controller_name}.L5X").write_bytes(l5x)


def print_planner_notes(state: PipelineState) -> None:
    print_list("Assumptions", state["assumptions"])
    print_list("Unsupported (not generated)", state["unsupported"])


def print_list(title: str, items: list[str]) -> None:
    print(f"{title}:")
    for item in items or ["none"]:
        print(f"  - {item}")


def print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        print(f"{issue.severity.value}: [{issue.rule}] {issue.message}", file=sys.stderr)


if __name__ == "__main__":
    entry()
