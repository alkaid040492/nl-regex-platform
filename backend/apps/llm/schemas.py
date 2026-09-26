from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RegexSpec:
    """What the LLM must produce for every transform type."""

    pattern: str
    explanation: str = ""
    # NORMALIZE only: Java replacement template using $1, $2 ... back-references
    replacement_template: str = ""
    # EXTRACT only: which capture group holds the value (0 = whole match)
    group: int = 0
    # populated by the cache layer, not the model
    cached: bool = field(default=False, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("cached", None)
        return d

    @classmethod
    def from_dict(cls, d: dict, *, cached: bool = False) -> "RegexSpec":
        return cls(
            pattern=str(d.get("pattern", "")),
            explanation=str(d.get("explanation", "")),
            replacement_template=str(d.get("replacement_template", "") or ""),
            group=int(d.get("group", 0) or 0),
            cached=cached,
        )
