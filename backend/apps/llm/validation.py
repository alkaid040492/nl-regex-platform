"""
Validate an LLM-generated regex before it is handed to Spark.

Three layers, cheapest first:
1. Syntax / dialect: compile with Python's engine, and reject or translate constructs that
   differ between Python and Java (`(?P<name>` → `(?<name>`, `(?P=name)` → `\\k<name>`).
   The final JVM compile check happens in the worker via py4j (engine.java_regex).
2. Static ReDoS check: walk the parsed regex tree and reject nested unbounded repetition
   such as (a+)+, (.*)*, (\\w+\\s?)* — the classic catastrophic-backtracking shape.
3. Dynamic check: run the pattern with the `regex` module's timeout against the sample
   values and a few adversarial strings. Anything that takes > REGEX_TIMEOUT_SECONDS is
   rejected. This catches slow patterns the static rule does not recognise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from re import _constants as sre_constants  # type: ignore[attr-defined]
from re import _parser as sre_parse  # type: ignore[attr-defined]

import regex as regex_mod

from apps.core.exceptions import AppError

REGEX_TIMEOUT_SECONDS = 1.0
MAX_PATTERN_LENGTH = 1000
ADVERSARIAL_STRINGS = (
    "a" * 5000,
    "a" * 3000 + "!",
    "ab" * 2500 + "!",
    "a@a." * 1200,
    "1-" * 2500 + "x",
    "1" * 4000 + "x",
    " " * 3000 + "x",
    "!" * 4000,
)


class InvalidRegex(AppError):
    code = "INVALID_REGEX"


class UnsafeRegex(AppError):
    code = "UNSAFE_REGEX"


@dataclass(frozen=True)
class ValidatedPattern:
    pattern: str  # Java-compatible
    groups: int


_PY_NAMED_GROUP = re.compile(r"\(\?P<([A-Za-z_][A-Za-z0-9_]*)>")
_PY_NAMED_BACKREF = re.compile(r"\(\?P=([A-Za-z_][A-Za-z0-9_]*)\)")
_UNSUPPORTED_IN_JAVA = [
    (re.compile(r"\(\?#"), "inline comments (?#...) are not supported"),
    (re.compile(r"\\A|\\Z"), "use \\b or ^/$ instead of \\A and \\Z"),
    (re.compile(r"\(\?<[=!]"), None),  # lookbehind is fine in Java; listed to document the decision
]


def to_java_syntax(pattern: str) -> str:
    pattern = _PY_NAMED_GROUP.sub(r"(?<\1>", pattern)
    pattern = _PY_NAMED_BACKREF.sub(r"\\k<\1>", pattern)
    return pattern


def _java_to_python_syntax(pattern: str) -> str:
    """The reverse mapping so we can compile the Java-flavoured pattern with Python's engine."""
    pattern = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)
    pattern = re.sub(r"\\k<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P=\1)", pattern)
    return pattern


def _has_nested_unbounded_repeat(parsed, inside_unbounded: bool = False) -> bool:
    for op, av in parsed:
        if op in (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT):
            _min, _max, sub = av
            unbounded = _max == sre_constants.MAXREPEAT or _max >= 1000
            if unbounded and inside_unbounded:
                return True
            if _has_nested_unbounded_repeat(sub, inside_unbounded or unbounded):
                return True
        elif op == sre_constants.SUBPATTERN:
            sub = av[-1]
            if _has_nested_unbounded_repeat(sub, inside_unbounded):
                return True
        elif op == sre_constants.BRANCH:
            for branch in av[1]:
                if _has_nested_unbounded_repeat(branch, inside_unbounded):
                    return True
        elif op in (sre_constants.ASSERT, sre_constants.ASSERT_NOT):
            if _has_nested_unbounded_repeat(av[1], inside_unbounded):
                return True
        elif op == sre_constants.ATOMIC_GROUP:
            if _has_nested_unbounded_repeat(av, inside_unbounded):
                return True
    return False


def validate_pattern(pattern: str, samples: list[str] | None = None, *, min_groups: int = 0) -> ValidatedPattern:
    """Return a Java-compatible pattern or raise InvalidRegex / UnsafeRegex."""
    if not pattern or not pattern.strip():
        raise InvalidRegex("The generated pattern is empty.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise InvalidRegex("The generated pattern is unreasonably long.")

    java_pattern = to_java_syntax(pattern)
    for rx, message in _UNSUPPORTED_IN_JAVA:
        if message and rx.search(java_pattern):
            raise InvalidRegex(f"Pattern uses a construct Spark cannot run: {message}.")

    py_pattern = _java_to_python_syntax(java_pattern)
    try:
        compiled = re.compile(py_pattern)
        parsed = sre_parse.parse(py_pattern)
    except re.error as exc:
        raise InvalidRegex(f"The generated pattern is not a valid regular expression: {exc}.") from None

    if compiled.groups < min_groups:
        raise InvalidRegex(f"The pattern must contain at least {min_groups} capture group(s); it has {compiled.groups}.")

    if _has_nested_unbounded_repeat(parsed):
        raise UnsafeRegex(
            "The pattern contains nested unbounded repetition (e.g. (a+)+), which can cause catastrophic backtracking."
        )

    _run_timed(py_pattern, list(samples or []) + list(ADVERSARIAL_STRINGS))
    return ValidatedPattern(pattern=java_pattern, groups=compiled.groups)


def _run_timed(py_pattern: str, inputs: list[str]) -> None:
    try:
        rx = regex_mod.compile(py_pattern)
    except regex_mod.error as exc:
        raise InvalidRegex(f"The generated pattern is not a valid regular expression: {exc}.") from None
    for text in inputs:
        try:
            rx.search(text, timeout=REGEX_TIMEOUT_SECONDS)
            rx.sub("x", text[:2000], timeout=REGEX_TIMEOUT_SECONDS)
        except TimeoutError:
            raise UnsafeRegex(
                "The pattern is too slow on realistic input (possible catastrophic backtracking). Try a more specific description."
            ) from None


# --- replacement template (NORMALIZE) -------------------------------------------

_TEMPLATE_REF = re.compile(r"\$(\d+)|\$\{(\d+)\}")


def validate_replacement_template(template: str, groups: int) -> str:
    """
    Check $n references exist and return a Java-safe template: literal `$` becomes `\\$`,
    literal `\\` becomes `\\\\`, `$n` back-references are kept.
    """
    if template is None or template == "":
        raise InvalidRegex("The normalization template is empty.")
    refs = [int(a or b) for a, b in _TEMPLATE_REF.findall(template)]
    bad = [n for n in refs if n < 0 or n > groups]
    if bad:
        raise InvalidRegex(f"The template references group ${bad[0]} but the pattern only has {groups} group(s).")

    out: list[str] = []
    i = 0
    while i < len(template):
        ch = template[i]
        if ch == "\\":
            # already-escaped dollar or backslash from the model: keep as-is
            if i + 1 < len(template) and template[i + 1] in "$\\":
                out.append(template[i : i + 2])
                i += 2
                continue
            out.append("\\\\")
        elif ch == "$":
            m = _TEMPLATE_REF.match(template, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
            out.append("\\$")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
