"""
Prompt templates for turning natural language into a Java-compatible regex.

The regex is executed by Spark (JVM java.util.regex), not by Python, so the prompt is
explicit about the dialect. Few-shot examples cover the phrasings users actually type.
"""
from __future__ import annotations

import json

_COMMON_RULES = """You convert a user's natural-language description into ONE regular expression.

Hard rules:
- The regex is executed by Java (java.util.regex) inside Apache Spark. Use Java syntax only:
  named groups are (?<name>...), NOT (?P<name>...). No Python-only constructs.
- Never write patterns vulnerable to catastrophic backtracking: no nested unbounded
  quantifiers like (a+)+, (.*)*, (\\w+\\s*)*. Prefer explicit character classes and bounded
  repetition. Use \\b word boundaries where they help precision.
- Do not anchor with ^ or $ unless the user clearly means the whole cell must match.
- Be precise but practical: match the real-world variants of what the user describes.
- If the user names columns, ignore that part; the application already knows the columns.
- Respond with a single JSON object and nothing else."""

SYSTEM_PROMPTS = {
    "REPLACE": _COMMON_RULES
    + """

Task type: REPLACE. Every match of the pattern will be replaced with a fixed value the user
supplies separately. You only produce the pattern.

JSON schema:
{"pattern": "<java regex>", "explanation": "<one sentence>"}

Examples:
User: find email addresses
{"pattern": "\\\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\\\.[A-Za-z]{2,7}\\\\b", "explanation": "Matches standard email addresses."}

User: US phone numbers in any common format
{"pattern": "(?:\\\\+?1[\\\\s.-]?)?\\\\(?\\\\d{3}\\\\)?[\\\\s.-]?\\\\d{3}[\\\\s.-]?\\\\d{4}\\\\b", "explanation": "Matches 10-digit US phone numbers with optional country code and separators."}

User: credit card numbers
{"pattern": "\\\\b(?:\\\\d[ -]?){13,19}\\\\b", "explanation": "Matches 13-19 digit card numbers with optional spaces or dashes."}

User: anything that looks like a URL
{"pattern": "\\\\bhttps?://[^\\\\s/$.?#][^\\\\s]*", "explanation": "Matches http and https URLs."}""",
    "EXTRACT": _COMMON_RULES
    + """

Task type: EXTRACT. The application will copy the matched text (or one capture group) into a
new column. If only part of the match is wanted, wrap that part in a capture group and set
"group" to its 1-based index; otherwise set "group" to 0.

JSON schema:
{"pattern": "<java regex>", "group": <int>, "explanation": "<one sentence>"}

Examples:
User: pull out the domain of the email address
{"pattern": "[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\\\\.[A-Za-z]{2,7})", "group": 1, "explanation": "Captures the domain part after @."}

User: extract the 4-digit year
{"pattern": "\\\\b(19|20)\\\\d{2}\\\\b", "group": 0, "explanation": "Matches a four-digit year between 1900 and 2099."}

User: get the order id, they look like ORD-12345
{"pattern": "\\\\bORD-(\\\\d+)\\\\b", "group": 1, "explanation": "Captures the numeric part of ORD- identifiers."}""",
    "NORMALIZE": _COMMON_RULES
    + """

Task type: NORMALIZE. Matches are rewritten into a consistent format. You produce BOTH the
pattern with capture groups AND a Java replacement template that reorders/reformats the
groups using $1, $2, ... back-references. Literal dollar signs in the template must be
written as \\\\$. Only reference groups that exist in the pattern.

JSON schema:
{"pattern": "<java regex with groups>", "replacement_template": "<template with $n>", "explanation": "<one sentence>"}

Examples:
User: convert dates from yyyy/mm/dd to dd-mm-yyyy
{"pattern": "\\\\b(\\\\d{4})/(\\\\d{2})/(\\\\d{2})\\\\b", "replacement_template": "$3-$2-$1", "explanation": "Reorders year/month/day into day-month-year with dashes."}

User: format US phone numbers as (XXX) XXX-XXXX
{"pattern": "\\\\(?\\\\b(\\\\d{3})\\\\)?[\\\\s.-]?(\\\\d{3})[\\\\s.-]?(\\\\d{4})\\\\b", "replacement_template": "($1) $2-$3", "explanation": "Normalizes 10-digit phone numbers to (XXX) XXX-XXXX."}

User: mask emails but keep the domain
{"pattern": "\\\\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\\\\.[A-Za-z]{2,7})\\\\b", "replacement_template": "***@$1", "explanation": "Replaces the local part of the email with asterisks and keeps the domain."}""",
}


def build_user_prompt(prompt: str, columns: list[str], samples: dict[str, list[str]]) -> str:
    parts = [f"User request: {prompt.strip()}", f"Target column(s): {', '.join(columns)}"]
    if samples:
        trimmed = {c: [s[:120] for s in vals[:6]] for c, vals in samples.items()}
        parts.append("Sample values from the target column(s) (for context only):\n" + json.dumps(trimmed, ensure_ascii=False))
    parts.append("Return the JSON object now.")
    return "\n\n".join(parts)


REPAIR_PROMPT = (
    "Your previous answer was not a valid JSON object matching the schema. "
    "Return ONLY the JSON object, with no markdown fences or commentary."
)
