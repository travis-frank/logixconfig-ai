import pytest

from logixconfig.models import Equipment
from logixconfig.templates import tags_for
from logixconfig.validator import Severity, has_errors, validate, validate_equipment


def equipment(*names: str) -> list[Equipment]:
    return [Equipment(name=name, type="pump") for name in names]


def rules_for(name: str) -> set[str]:
    return {issue.rule for issue in validate_equipment(equipment(name))}


@pytest.mark.parametrize("name", ["P101", "XV101", "LT_101", "PT1", "A", "P" * 20])
def test_valid_ids(name: str) -> None:
    assert validate_equipment(equipment(name)) == []


def test_empty_list_is_an_error() -> None:
    issues = validate_equipment([])
    assert [(issue.rule, issue.severity) for issue in issues] == [("no_equipment", Severity.ERROR)]
    assert has_errors(issues)


@pytest.mark.parametrize("name", ["101P", "_P101", "9"])
def test_must_start_with_a_letter(name: str) -> None:
    assert "first_char" in rules_for(name)


def test_leading_underscore_is_allowed_for_tags_but_not_equipment() -> None:
    assert rules_for("_P101") == {"first_char"}


@pytest.mark.parametrize("name", ["P-101", "P 101", "P.101", "Pümp"])
def test_only_letters_digits_underscores(name: str) -> None:
    assert "allowed_chars" in rules_for(name)


def test_20_chars_allowed_21_rejected() -> None:
    assert "max_length" not in rules_for("P" * 20)
    assert "max_length" in rules_for("P" * 21)


def test_double_underscore_rejected() -> None:
    assert "consecutive_underscores" in rules_for("P__101")


def test_trailing_underscore_rejected() -> None:
    assert "trailing_underscore" in rules_for("P101_")


def test_case_insensitive_duplicates() -> None:
    issues = validate_equipment(equipment("P101", "XV101", "p101"))
    assert [(issue.rule, issue.name) for issue in issues] == [("duplicate", "p101")]
    assert "Equipment ID 'p101' duplicates 'P101'" in issues[0].message


def test_messages_say_equipment_id() -> None:
    [issue] = validate_equipment(equipment("P101_"))
    assert issue.message.startswith("Equipment ID 'P101_'")


@pytest.mark.parametrize("kind", ["pump", "valve", "level_transmitter", "pressure_transmitter"])
def test_max_length_id_still_gives_valid_tag_names(kind: str) -> None:
    item = Equipment(name="A" * 20, type=kind, description="Long ID")
    assert validate_equipment([item]) == []
    assert validate(tags_for(item)) == []
