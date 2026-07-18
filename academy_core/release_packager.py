from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Tuple

from .release_candidate_models import ReleaseBundleManifest


class ReleasePackager:
    def build_manifest(
        self,
        *,
        root: Path,
        relative_files: Iterable[str],
        version: str,
        commit: str,
        build_id: str,
        test_count: int,
        test_status: str,
        frozen: bool,
    ) -> ReleaseBundleManifest:
        selected = tuple(sorted(set(relative_files)))
        checksums = {}
        for relative in selected:
            path = root / relative
            if not path.is_file():
                raise FileNotFoundError(relative)
            checksums[relative] = self._sha256(path.read_bytes())

        canonical = json.dumps(
            {
                "version": version,
                "commit": commit,
                "build_id": build_id,
                "files": selected,
                "checksums": checksums,
                "test_count": test_count,
                "test_status": test_status,
                "frozen": frozen,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return ReleaseBundleManifest(
            version=version,
            commit=commit,
            build_id=build_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            files=selected,
            checksums=checksums,
            bundle_checksum=self._sha256(canonical.encode("utf-8")),
            test_count=test_count,
            test_status=test_status,
            frozen=frozen,
        )

    def verify(self, root: Path, manifest: ReleaseBundleManifest) -> bool:
        for relative, expected in manifest.checksums.items():
            path = root / relative
            if not path.is_file():
                return False
            if self._sha256(path.read_bytes()) != expected:
                return False
        return True

    @staticmethod
    def _sha256(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()
