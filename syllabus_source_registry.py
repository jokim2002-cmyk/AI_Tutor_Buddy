from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


class SourceGovernanceError(ValueError):
    """Raised when a syllabus source fails provenance or reuse validation."""


SUPPORTED_BOARDS = {"GSEB", "CBSE"}
SUPPORTED_STANDARDS = set(range(1, 11))
REVIEW_STATUSES = {
    "discovered",
    "verified_official",
    "approved_for_metadata",
    "approved_for_content",
    "blocked",
}
REUSE_STATUSES = {
    "verification_required",
    "metadata_only",
    "permission_granted",
    "open_license",
    "public_domain",
    "blocked",
}
CONTENT_REUSE_STATUSES = {
    "permission_granted",
    "open_license",
    "public_domain",
}
ALLOWED_OFFICIAL_HOSTS = {
    "GSEB": {
        "website.gseb.org",
        "gsbstb.online",
    },
    "CBSE": {
        "cbseacademic.nic.in",
        "ncert.nic.in",
        "www.ncert.nic.in",
    },
}


def _clean(value: object, *, max_length: int = 500) -> str:
    return " ".join(str(value or "").split())[:max_length]


@dataclass(frozen=True)
class OfficialSourceRecord:
    source_id: str
    board: str
    authority: str
    source_url: str
    standards: tuple[int, ...]
    mediums: tuple[str, ...]
    content_scope: str
    academic_year: str
    review_status: str
    reuse_status: str
    license_reference: str = ""
    sha256_required: bool = True
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OfficialSourceRecord":
        try:
            standards = tuple(int(item) for item in payload.get("standards", []))
        except (TypeError, ValueError) as exc:
            raise SourceGovernanceError("standards must contain numbers from 1 to 10") from exc

        record = cls(
            source_id=_clean(payload.get("source_id"), max_length=120),
            board=_clean(payload.get("board"), max_length=20).upper(),
            authority=_clean(payload.get("authority"), max_length=200),
            source_url=_clean(payload.get("source_url"), max_length=1_000),
            standards=standards,
            mediums=tuple(
                _clean(item, max_length=60)
                for item in payload.get("mediums", [])
                if _clean(item, max_length=60)
            ),
            content_scope=_clean(payload.get("content_scope"), max_length=120),
            academic_year=_clean(payload.get("academic_year"), max_length=40),
            review_status=_clean(payload.get("review_status"), max_length=40),
            reuse_status=_clean(payload.get("reuse_status"), max_length=40),
            license_reference=_clean(payload.get("license_reference"), max_length=1_000),
            sha256_required=bool(payload.get("sha256_required", True)),
            notes=_clean(payload.get("notes"), max_length=2_000),
        )
        record.validate()
        return record

    @property
    def host(self) -> str:
        return (urlparse(self.source_url).hostname or "").casefold()

    @property
    def content_import_allowed(self) -> bool:
        return (
            self.review_status == "approved_for_content"
            and self.reuse_status in CONTENT_REUSE_STATUSES
            and bool(self.license_reference)
            and self.sha256_required
        )

    def validate(self) -> None:
        if not self.source_id:
            raise SourceGovernanceError("source_id is required")
        if self.board not in SUPPORTED_BOARDS:
            raise SourceGovernanceError("board must be GSEB or CBSE")
        if not self.authority:
            raise SourceGovernanceError("authority is required")

        parsed = urlparse(self.source_url)
        if parsed.scheme.casefold() != "https":
            raise SourceGovernanceError("official source URL must use HTTPS")
        if self.host not in ALLOWED_OFFICIAL_HOSTS[self.board]:
            raise SourceGovernanceError(
                f"host {self.host or '<missing>'} is not allowlisted for {self.board}"
            )

        if not self.standards:
            raise SourceGovernanceError("at least one standard is required")
        if any(item not in SUPPORTED_STANDARDS for item in self.standards):
            raise SourceGovernanceError("standards must be between 1 and 10")
        if len(set(self.standards)) != len(self.standards):
            raise SourceGovernanceError("standards cannot contain duplicates")

        if not self.content_scope:
            raise SourceGovernanceError("content_scope is required")
        if not self.academic_year:
            raise SourceGovernanceError("academic_year is required")
        if self.review_status not in REVIEW_STATUSES:
            raise SourceGovernanceError(
                f"unsupported review_status: {self.review_status}"
            )
        if self.reuse_status not in REUSE_STATUSES:
            raise SourceGovernanceError(
                f"unsupported reuse_status: {self.reuse_status}"
            )

        if self.review_status == "approved_for_content":
            if self.reuse_status not in CONTENT_REUSE_STATUSES:
                raise SourceGovernanceError(
                    "content approval requires permission, an open license, or public-domain status"
                )
            if not self.license_reference:
                raise SourceGovernanceError(
                    "approved content requires a license or permission reference"
                )
            if not self.sha256_required:
                raise SourceGovernanceError(
                    "approved content imports must require a SHA-256 fingerprint"
                )

        if self.reuse_status in {"verification_required", "metadata_only", "blocked"}:
            if self.review_status == "approved_for_content":
                raise SourceGovernanceError(
                    "restricted or unverified sources cannot be approved for content"
                )


class OfficialSourceRegistry:
    def __init__(self, records: tuple[OfficialSourceRecord, ...]):
        self.records = records
        self._by_id = {record.source_id: record for record in records}
        if len(self._by_id) != len(records):
            raise SourceGovernanceError("source_id values must be unique")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "OfficialSourceRegistry":
        schema_version = int(payload.get("schema_version", 0))
        if schema_version != 1:
            raise SourceGovernanceError("official source inventory schema_version must be 1")
        records = tuple(
            OfficialSourceRecord.from_dict(item)
            for item in payload.get("sources", [])
        )
        if not records:
            raise SourceGovernanceError("official source inventory cannot be empty")
        return cls(records)

    @classmethod
    def load(cls, path: str | Path) -> "OfficialSourceRegistry":
        source_path = Path(path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceGovernanceError(
                f"unable to read official source inventory: {exc}"
            ) from exc
        return cls.from_payload(payload)

    def get(self, source_id: str) -> OfficialSourceRecord | None:
        return self._by_id.get(_clean(source_id, max_length=120))

    def for_board(self, board: str) -> tuple[OfficialSourceRecord, ...]:
        normalized = _clean(board, max_length=20).upper()
        if normalized not in SUPPORTED_BOARDS:
            raise SourceGovernanceError("board must be GSEB or CBSE")
        return tuple(record for record in self.records if record.board == normalized)

    def approved_for_content(self) -> tuple[OfficialSourceRecord, ...]:
        return tuple(record for record in self.records if record.content_import_allowed)

    def coverage_matrix(self) -> dict[str, dict[int, list[str]]]:
        matrix: dict[str, dict[int, list[str]]] = {
            board: {standard: [] for standard in range(1, 11)}
            for board in sorted(SUPPORTED_BOARDS)
        }
        for record in self.records:
            for standard in record.standards:
                matrix[record.board][standard].append(record.source_id)
        return matrix
