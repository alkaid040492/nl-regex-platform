import pytest

from apps.llm.validation import (
    InvalidRegex,
    UnsafeRegex,
    to_java_syntax,
    validate_pattern,
    validate_replacement_template,
)

from .conftest import EMAIL_PATTERN


@pytest.mark.parametrize(
    "pattern",
    [
        EMAIL_PATTERN,
        r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
        r"(\d{4})/(\d{2})/(\d{2})",
        r"https?://[^\s/$.?#][^\s]*",
        r"\b(?:\d[ -]?){13,19}\b",
        r"(?i)\bconfidential\b",
        r"(?<year>\d{4})-(?<month>\d{2})",
    ],
)
def test_reasonable_patterns_pass(pattern):
    v = validate_pattern(pattern, ["john@example.com", "2024/01/05"])
    assert v.pattern


@pytest.mark.parametrize("pattern", [r"(a+)+", r"(.*)*", r"(\w+\s?)*$", r"((ab)*)+", r"(x+x+)+y", r"^(\d+)*$"])
def test_nested_unbounded_quantifiers_rejected(pattern):
    with pytest.raises(UnsafeRegex):
        validate_pattern(pattern)


@pytest.mark.parametrize("pattern", ["[unclosed", "(?P<a>x)(?P<a>y)", "*abc", ""])
def test_invalid_syntax_rejected(pattern):
    with pytest.raises(InvalidRegex):
        validate_pattern(pattern)


def test_python_named_groups_translated_to_java():
    v = validate_pattern(r"(?P<user>\w+)@(?P<host>\w+)(?P=user)", ["a@b"])
    assert v.pattern == r"(?<user>\w+)@(?<host>\w+)\k<user>"
    assert v.groups == 2
    assert to_java_syntax(r"(?P<x>a)") == r"(?<x>a)"


def test_min_groups_enforced():
    with pytest.raises(InvalidRegex):
        validate_pattern(r"\d{4}/\d{2}/\d{2}", min_groups=3)


def test_java_only_constructs_rejected():
    with pytest.raises(InvalidRegex):
        validate_pattern(r"\Afoo\Z")


def test_template_validation_and_escaping():
    assert validate_replacement_template("$3-$2-$1", 3) == "$3-$2-$1"
    assert validate_replacement_template("costs $ and \\ and $1", 1) == r"costs \$ and \\ and $1"
    assert validate_replacement_template("keep \\$ literal", 0) == "keep \\$ literal"
    with pytest.raises(InvalidRegex):
        validate_replacement_template("$4", 3)
    with pytest.raises(InvalidRegex):
        validate_replacement_template("", 1)
