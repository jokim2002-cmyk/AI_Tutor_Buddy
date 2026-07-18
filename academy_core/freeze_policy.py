from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True)
class FreezeDecision:
    allowed: bool
    blocked_paths: Tuple[str, ...]
    reason: str


class ReleaseFreezePolicy:
    ALLOWED_PREFIXES = (
        "docs/",
        "release/",
        ".github/",
    )
    ALLOWED_FILES = (
        "README.md",
        "CHANGELOG.md",
        "RELEASE_NOTES.md",
    )

    def evaluate(self, changed_paths: Iterable[str], *, frozen: bool) -> FreezeDecision:
        changed = tuple(sorted(set(path.replace("\\", "/") for path in changed_paths)))
        if not frozen:
            return FreezeDecision(True, (), "Release freeze is not active")

        blocked = []
        for path in changed:
            if path in self.ALLOWED_FILES:
                continue
            if any(path.startswith(prefix) for prefix in self.ALLOWED_PREFIXES):
                continue
            blocked.append(path)

        return FreezeDecision(
            allowed=not blocked,
            blocked_paths=tuple(blocked),
            reason=(
                "Only release documentation and CI metadata changes are allowed during freeze"
                if blocked
                else "All changes comply with release freeze policy"
            ),
        )
