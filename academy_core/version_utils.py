from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def get_project_version(root: Path | None = None) -> str:
    if root is None:
        root = Path.cwd()
    pyproject_path = Path(root) / "pyproject.toml"
    if not pyproject_path.exists():
        raise ValueError(f"pyproject.toml not found at {pyproject_path}")

    content = pyproject_path.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            version = data.get("project", {}).get("version", "").strip()
            if version:
                return version
        except Exception as exc:
            raise ValueError(f"Failed to parse pyproject.toml: {exc}") from exc

    match = re.search(r'\[project\][^\[]*version\s*=\s*"([^"]+)"', content)
    if match:
        return match.group(1).strip()

    raise ValueError("Could not extract valid version from pyproject.toml")
