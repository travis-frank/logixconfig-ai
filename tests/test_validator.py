import pytest

from logixconfig.models import Equipment, Tag
from logixconfig.templates import tags_for
from logixconfig.validator import Severity, has_errors, validate


def make_tag(name: str, description: str = "Some tag") -> Tag:
    return Tag(name=name, data_type="BOOL", description=description, equipment="EQ")


def rules_for(name: str) -> set[str]:
    return {issue.rule for issue in validate([make_tag(name)])}


@pytest.mark.parametrize("name", ["P101_Run_Cmd", "_Internal", "a", "A" * 40, "Tank1_Level"])
def test_valid_names_have_no_issues(name: str) -> None:
    assert validate([make_tag(name)]) == []


def test_empty_name() -> None:
    assert rules_for("") == {"empty_name"}


@pytest.mark.parametrize("name", ["1Pump", "9_Run"])
def test_must_start_with_letter_or_underscore(name: str) -> None:
    assert "first_char" in rules_for(name)


@pytest.mark.parametrize("name", ["Pump-1", "Pump 1", "Pump.Run", "Pümp"])
def test_only_letters_digits_underscores(name: str) -> None:
    assert "allowed_chars" in rules_for(name)


def test_40_char_name_is_allowed() -> None:
    assert "max_length" not in rules_for("A" * 40)


def test_41_char_name_is_rejected() -> None:
    assert "max_length" in rules_for("A" * 41)


def test_double_underscore_is_rejected() -> None:
    assert "consecutive_underscores" in rules_for("P101__Run")


def test_trailing_underscore_is_rejected() -> None:
    assert "trailing_underscore" in rules_for("P101_Run_")


def test_one_name_can_break_several_rules() -> None:
    assert rules_for("1Bad__Name_") == {"first_char", "consecutive_underscores", "trailing_underscore"}


def test_exact_duplicates_are_rejected() -> None:
    issues = validate([make_tag("P101_Run"), make_tag("P101_Run")])
    assert [issue.rule for issue in issues] == ["duplicate"]


def test_case_different_duplicates_are_rejected() -> None:
    issues = validate([make_tag("P101_Run"), make_tag("p101_RUN")])
    assert len(issues) == 1
    assert issues[0].rule == "duplicate"
    assert issues[0].tag_name == "p101_RUN"
    assert "P101_Run" in issues[0].message


def test_three_copies_give_two_duplicate_errors() -> None:
    issues = validate([make_tag("X"), make_tag("x"), make_tag("X")])
    assert [issue.rule for issue in issues] == ["duplicate", "duplicate"]


@pytest.mark.parametrize("description", ["", "   "])
def test_missing_description_is_a_warning(description: str) -> None:
    issues = validate([make_tag("P101_Run", description=description)])
    assert [(issue.rule, issue.severity) for issue in issues] == [("missing_description", Severity.WARNING)]


def test_512_char_description_is_allowed() -> None:
    assert validate([make_tag("P101_Run", description="d" * 512)]) == []


def test_513_char_description_is_an_error() -> None:
    issues = validate([make_tag("P101_Run", description="d" * 513)])
    assert [(issue.rule, issue.severity) for issue in issues] == [("description_too_long", Severity.ERROR)]


def test_long_equipment_description_makes_tag_description_too_long() -> None:
    tags = tags_for(Equipment(name="P101", type="pump", description="d" * 501))
    too_long = {issue.tag_name for issue in validate(tags) if issue.rule == "description_too_long"}
    assert too_long == {"P101_Run_Cmd", "P101_Run_Fb"}


def test_has_errors_ignores_warnings() -> None:
    warnings_only = validate([make_tag("P101_Run", description="")])
    assert warnings_only
    assert not has_errors(warnings_only)


def test_has_errors_detects_errors() -> None:
    assert has_errors(validate([make_tag("1Bad")]))


def test_has_errors_on_empty_list() -> None:
    assert not has_errors([])


def test_empty_tag_list_is_valid() -> None:
    assert validate([]) == []


def test_template_tags_pass_validation() -> None:
    tags = tags_for(Equipment(name="P101", type="pump", description="Feed pump"))
    assert validate(tags) == []


def test_long_equipment_name_makes_template_tag_too_long() -> None:
    tags = tags_for(Equipment(name="A" * 32, type="valve", description="Long valve"))
    too_long = {issue.tag_name for issue in validate(tags) if issue.rule == "max_length"}
    assert too_long == {"A" * 32 + "_Open_Cmd", "A" * 32 + "_Closed_Fb"}
