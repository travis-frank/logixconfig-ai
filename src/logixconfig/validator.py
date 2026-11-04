"""Deterministic checks for equipment IDs, Logix tag names, and tag descriptions."""

import re
from collections.abc import Callable
from enum import Enum

from pydantic import BaseModel

from logixconfig.models import Equipment, Tag

MAX_TAG_NAME_LENGTH = 40
MAX_EQUIPMENT_ID_LENGTH = 20
MAX_DESCRIPTION_LENGTH = 512  # Not stated in 1756-RM014D; from secondary sources. See 1756-PM001.

_ALLOWED_CHARS = re.compile(r"[A-Za-z0-9_]+")


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Issue(BaseModel):
    name: str
    severity: Severity
    rule: str
    message: str


NameRule = Callable[[str], str | None]


def check_letter_or_underscore_first(name: str) -> str | None:
    if not (name[0].isascii() and (name[0].isalpha() or name[0] == "_")):
        return "must start with a letter or underscore"
    return None


def check_letter_first(name: str) -> str | None:
    if not (name[0].isascii() and name[0].isalpha()):
        return "must start with a letter"
    return None


def check_allowed_chars(name: str) -> str | None:
    if not _ALLOWED_CHARS.fullmatch(name):
        return "may only contain letters, digits, and underscores"
    return None


def max_length(limit: int) -> NameRule:
    def check(name: str) -> str | None:
        if len(name) > limit:
            return f"is {len(name)} characters, max is {limit}"
        return None

    return check


def check_consecutive_underscores(name: str) -> str | None:
    if "__" in name:
        return "must not contain consecutive underscores"
    return None


def check_trailing_underscore(name: str) -> str | None:
    if name.endswith("_"):
        return "must not end with an underscore"
    return None


TAG_NAME_RULES: dict[str, NameRule] = {
    "first_char": check_letter_or_underscore_first,
    "allowed_chars": check_allowed_chars,
    "max_length": max_length(MAX_TAG_NAME_LENGTH),
    "consecutive_underscores": check_consecutive_underscores,
    "trailing_underscore": check_trailing_underscore,
}

EQUIPMENT_ID_RULES: dict[str, NameRule] = {
    "first_char": check_letter_first,
    "allowed_chars": check_allowed_chars,
    "max_length": max_length(MAX_EQUIPMENT_ID_LENGTH),
    "consecutive_underscores": check_consecutive_underscores,
    "trailing_underscore": check_trailing_underscore,
}


def rule_issues(name: str, label: str, rules: dict[str, NameRule]) -> list[Issue]:
    if not name:
        return [_error(name, "empty_name", f"{label} must not be empty")]
    issues = []
    for rule, check in rules.items():
        problem = check(name)
        if problem:
            issues.append(_error(name, rule, f"{label} '{name}' {problem}"))
    return issues


def name_issues(name: str, label: str = "Tag name") -> list[Issue]:
    return rule_issues(name, label, TAG_NAME_RULES)


def duplicate_issues(names: list[str], label: str) -> list[Issue]:
    first_seen: dict[str, str] = {}
    issues = []
    for name in names:
        key = name.lower()
        if key in first_seen:
            message = f"{label} '{name}' duplicates '{first_seen[key]}' (names are case-insensitive)"
            issues.append(_error(name, "duplicate", message))
        else:
            first_seen[key] = name
    return issues


def description_issues(tag: Tag) -> list[Issue]:
    if not tag.description.strip():
        message = f"Tag '{tag.name}' has no description"
        return [Issue(name=tag.name, severity=Severity.WARNING, rule="missing_description", message=message)]
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
    issues.extend(duplicate_issues([tag.name for tag in tags], "Tag name"))
    return issues


def validate_equipment(equipment: list[Equipment]) -> list[Issue]:
    if not equipment:
        return [_error("", "no_equipment", "Equipment list is empty; at least one item is required")]
    issues = []
    for item in equipment:
        issues.extend(rule_issues(item.name, "Equipment ID", EQUIPMENT_ID_RULES))
    issues.extend(duplicate_issues([item.name for item in equipment], "Equipment ID"))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)


def _error(name: str, rule: str, message: str) -> Issue:
    return Issue(name=name, severity=Severity.ERROR, rule=rule, message=message)
