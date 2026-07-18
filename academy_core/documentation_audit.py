from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple


class DocumentationAuditor:
    def find_missing(self, root: Path, required: Iterable[str]) -> Tuple[str, ...]:
        return tuple(sorted(name for name in required if not (root / name).is_file()))

    def find_empty(self, root: Path, files: Iterable[str]) -> Tuple[str, ...]:
        empty = []
        for name in files:
            path = root / name
            if path.is_file() and not path.read_text(encoding="utf-8").strip():
                empty.append(name)
        return tuple(sorted(empty))

    def validate_version_mentions(
        self,
        root: Path,
        expected_version: str,
        files: Iterable[str],
    ) -> Dict[str, bool]:
        result = {}
        for name in files:
            path = root / name
            if not path.is_file():
                result[name] = False
                continue
            result[name] = expected_version in path.read_text(encoding="utf-8")
        return result
