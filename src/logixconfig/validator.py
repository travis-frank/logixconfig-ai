"""Deterministic checks for Logix tag names and descriptions."""

import re
from collections.abc import Callable
from enum import Enum

from pydantic import BaseModel

from logixconfig.models import Tag

MAX_TAG_NAME_LENGTH = 40
MAX_DESCRIPTION_LENGTH = 512  # Studio 5000 tag description limit; confirm against 1756-RM014

_ALLOWED_CHARS = re.compile(r"[A-Za-z0-9_]+")
_VALID_FIRST_CHAR = re.compile(r"[A-Za-z_]")


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Issue(BaseModel):
    tag_name: str
    severity: Severity
    rule: str
    message: str


NameRule = Callable[[str], str | None]


def check_first_char(name: str) -> str | None:
    if not _VALID_FIRST_CHAR.fullmatch(name[0]):
        return "must start with a letter or underscore"
    return None


def check_allowed_chars(name: str) -> str | None:
    if not _ALLOWED_CHARS.fullmatch(name):
        return "may only contain letters, digits, and underscores"
    return None


def check_length(name: str) -> str | None:
    if len(name) > MAX_TAG_NAME_LENGTH:
        return f"is {len(name)} characters, max is {MAX_TAG_NAME_LENGTH}"
    return None


def check_consecutive_underscores(name: str) -> str | None:
    if "__" in name:
        return "must not contain consecutive underscores"
    return None


def check_trailing_underscore(name: str) -> str | None:
    if name.endswith("_"):
        return "must not end with an underscore"
    return None


NAME_RULES: dict[str, NameRule] = {
    "first_char": check_first_char,
    "allowed_chars": check_allowed_chars,
    "max_length": check_length,
    "consecutive_underscores": check_consecutive_underscores,
    "trailing_underscore": check_trailing_underscore,
}


def name_issues(name: str, label: str = "Tag name") -> list[Issue]:
    if not name:
        return [_error(name, "empty_name", f"{label} must not be empty")]
    issues = []
    for rule, check in NAME_RULES.items():
        problem = check(name)
        if problem:
            issues.append(_error(name, rule, f"{label} '{name}' {problem}"))
    return issues


def duplicate_issues(tags: list[Tag]) -> list[Issue]:
    first_seen: dict[str, str] = {}
    issues = []
    for tag in tags:
        key = tag.name.lower()
        if key in first_seen:
            message = f"Tag name '{tag.name}' duplicates '{first_seen[key]}' (names are case-insensitive)"
            issues.append(_error(tag.name, "duplicate", message))
        else:
            first_seen[key] = tag.name
    return issues


def description_issues(tag: Tag) -> list[Issue]:
    if not tag.description.strip():
        message = f"Tag '{tag.name}' has no description"
        return [Issue(tag_name=tag.name, severity=Severity.WARNING, rule="missing_description", message=message)]
    if len(tag.description) > MAX_DESCRIPTION_LENGTH:
        message = (
            f"Tag '{tag.name}' description is {len(tag.description)} characters, "
            f"max is {MAX_DESCRIPTION_LENGTH}"
        )
        return [_error(tag.name, "description_too_long", message)]
    return []


def validate(tags: list[Tag]) -> list[Issue]:
    issues = []
    for tag in tags:
        issues.extend(name_issues(tag.name))
        issues.extend(description_issues(tag))
    issues.extend(duplicate_issues(tags))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)


def _error(tag_name: str, rule: str, message: str) -> Issue:
    return Issue(tag_name=tag_name, severity=Severity.ERROR, rule=rule, message=message)
