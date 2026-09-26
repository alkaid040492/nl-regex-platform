"""
Logging filter that masks anything that looks like an AWS credential or API key.

Defence in depth: code never logs credentials on purpose, but a stack trace or a
misplaced repr() could. This filter rewrites the formatted message before output.
"""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"(?<![A-Z0-9])(AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),  # AWS access key id
    re.compile(r"(?i)(secret[_-]?(access[_-]?)?key|password|api[_-]?key|authorization)([\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)"),
    re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),  # OpenRouter key
    re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"),  # 40-char base64 (AWS secret shape)
]


def mask(text: str) -> str:
    text = _PATTERNS[0].sub("****MASKED_KEY_ID****", text)
    text = _PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(3)}****", text)
    text = _PATTERNS[2].sub("sk-or-****", text)
    text = _PATTERNS[3].sub("****MASKED_SECRET****", text)
    return text


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                record.msg = record.getMessage()
                record.args = ()
            if isinstance(record.msg, str):
                record.msg = mask(record.msg)
        except Exception:  # never let logging break the app
            pass
        return True
