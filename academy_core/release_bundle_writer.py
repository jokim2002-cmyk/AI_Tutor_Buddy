from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable


class ReleaseBundleWriter:
    def write(
        self,
        *,
        root: Path,
        output_zip: Path,
        relative_files: Iterable[str],
        extra_files: Iterable[Path] = (),
    ) -> Path:
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        if output_zip.exists():
            output_zip.unlink()

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in sorted(set(relative_files)):
                source = root / relative
                if not source.is_file():
                    raise FileNotFoundError(relative)
                archive.write(source, relative)
            for source in sorted(set(extra_files), key=lambda p: str(p)):
                if not source.is_file():
                    raise FileNotFoundError(str(source))
                archive.write(source, f"release/{source.name}")
        return output_zip

    def verify_readable(self, output_zip: Path) -> bool:
        try:
            with zipfile.ZipFile(output_zip, "r") as archive:
                return archive.testzip() is None and bool(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
