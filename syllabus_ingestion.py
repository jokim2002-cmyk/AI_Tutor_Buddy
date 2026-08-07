from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syllabus_source_registry import OfficialSourceRegistry


class IngestionError(RuntimeError):
    """Base error for immutable syllabus ingestion."""


class IngestionValidationError(IngestionError):
    """Raised when an ingestion request is invalid or unauthorized."""


class DuplicateIngestionError(IngestionError):
    """Raised when the exact immutable revision already exists."""


class EditionConflictError(IngestionError):
    """Raised when one package edition points at different immutable content."""


class IntegrityError(IngestionError):
    """Raised when stored bytes no longer match the recorded checksum."""


class RollbackError(IngestionError):
    """Raised when a requested rollback cannot be completed safely."""


class IngestionLockError(IngestionError):
    """Raised when another ingestion mutation owns the store lock."""


INGESTION_MODES = {"metadata", "content"}
PACKAGE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,159}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _clean(value: object, *, max_length: int) -> str:
    return " ".join(str(value or "").split())[:max_length]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_json_read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"unable to read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"JSON object expected in {path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("wb") as handle:
            encoded = _canonical_json(payload) + b"\n"
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class IngestionArtifact:
    name: str
    role: str
    media_type: str
    sha256: str
    size_bytes: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IngestionArtifact":
        artifact = cls(
            name=_clean(payload.get("name"), max_length=240),
            role=_clean(payload.get("role"), max_length=80),
            media_type=_clean(payload.get("media_type"), max_length=160),
            sha256=_clean(payload.get("sha256"), max_length=64).casefold(),
            size_bytes=int(payload.get("size_bytes", -1)),
        )
        artifact.validate()
        return artifact

    def validate(self) -> None:
        if not self.name or self.name in {".", ".."}:
            raise IngestionValidationError("artifact name is required")
        if Path(self.name).name != self.name or "/" in self.name or "\\" in self.name:
            raise IngestionValidationError("artifact name must be a plain filename")
        if not self.role:
            raise IngestionValidationError("artifact role is required")
        if not self.media_type:
            raise IngestionValidationError("artifact media_type is required")
        if not SHA256_RE.fullmatch(self.sha256):
            raise IngestionValidationError("artifact sha256 must be 64 lowercase hex characters")
        if self.size_bytes < 0:
            raise IngestionValidationError("artifact size_bytes cannot be negative")


@dataclass(frozen=True)
class IngestionManifest:
    schema_version: int
    revision_id: str
    package_key: str
    board: str
    medium: str
    standard: int
    subject: str
    academic_year: str
    edition: str
    source_id: str
    ingestion_mode: str
    artifacts: tuple[IngestionArtifact, ...]
    previous_revision_id: str
    created_at: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IngestionManifest":
        manifest = cls(
            schema_version=int(payload.get("schema_version", 0)),
            revision_id=_clean(payload.get("revision_id"), max_length=64).casefold(),
            package_key=_clean(payload.get("package_key"), max_length=160),
            board=_clean(payload.get("board"), max_length=20).upper(),
            medium=_clean(payload.get("medium"), max_length=80),
            standard=int(payload.get("standard", 0)),
            subject=_clean(payload.get("subject"), max_length=120),
            academic_year=_clean(payload.get("academic_year"), max_length=80),
            edition=_clean(payload.get("edition"), max_length=120),
            source_id=_clean(payload.get("source_id"), max_length=120),
            ingestion_mode=_clean(payload.get("ingestion_mode"), max_length=20).casefold(),
            artifacts=tuple(
                IngestionArtifact.from_dict(item)
                for item in payload.get("artifacts", [])
            ),
            previous_revision_id=_clean(
                payload.get("previous_revision_id"), max_length=64
            ).casefold(),
            created_at=_clean(payload.get("created_at"), max_length=80),
        )
        manifest.validate()
        if manifest.revision_id != manifest.calculate_revision_id():
            raise IntegrityError("manifest revision_id does not match canonical content")
        return manifest

    def validate(self) -> None:
        if self.schema_version != 1:
            raise IngestionValidationError("manifest schema_version must be 1")
        if not SHA256_RE.fullmatch(self.revision_id):
            raise IngestionValidationError("revision_id must be a SHA-256 hex digest")
        if not PACKAGE_KEY_RE.fullmatch(self.package_key):
            raise IngestionValidationError(
                "package_key must contain only letters, numbers, dots, underscores or hyphens"
            )
        if self.board not in {"GSEB", "CBSE"}:
            raise IngestionValidationError("board must be GSEB or CBSE")
        if not self.medium:
            raise IngestionValidationError("medium is required")
        if self.standard not in range(1, 11):
            raise IngestionValidationError("standard must be between 1 and 10")
        if not self.subject:
            raise IngestionValidationError("subject is required")
        if not self.academic_year:
            raise IngestionValidationError("academic_year is required")
        if not self.edition:
            raise IngestionValidationError("edition is required")
        if not self.source_id:
            raise IngestionValidationError("source_id is required")
        if self.ingestion_mode not in INGESTION_MODES:
            raise IngestionValidationError("ingestion_mode must be metadata or content")
        if not self.artifacts:
            raise IngestionValidationError("at least one artifact is required")
        names = [artifact.name.casefold() for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise IngestionValidationError("artifact filenames must be unique")
        if self.previous_revision_id and not SHA256_RE.fullmatch(
            self.previous_revision_id
        ):
            raise IngestionValidationError(
                "previous_revision_id must be empty or a SHA-256 digest"
            )
        if not self.created_at:
            raise IngestionValidationError("created_at is required")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_key": self.package_key,
            "board": self.board,
            "medium": self.medium,
            "standard": self.standard,
            "subject": self.subject,
            "academic_year": self.academic_year,
            "edition": self.edition,
            "source_id": self.source_id,
            "ingestion_mode": self.ingestion_mode,
            "artifacts": [
                asdict(artifact)
                for artifact in sorted(
                    self.artifacts,
                    key=lambda item: (item.name.casefold(), item.sha256),
                )
            ],
        }

    def calculate_revision_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.identity_payload()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision_id": self.revision_id,
            "package_key": self.package_key,
            "board": self.board,
            "medium": self.medium,
            "standard": self.standard,
            "subject": self.subject,
            "academic_year": self.academic_year,
            "edition": self.edition,
            "source_id": self.source_id,
            "ingestion_mode": self.ingestion_mode,
            "artifacts": [asdict(item) for item in self.artifacts],
            "previous_revision_id": self.previous_revision_id,
            "created_at": self.created_at,
        }


class _MutationLock(AbstractContextManager["_MutationLock"]):
    def __init__(self, path: Path, timeout_seconds: float):
        self.path = path
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.token = uuid.uuid4().hex
        self.acquired = False

    def __enter__(self) -> "_MutationLock":
        deadline = time.monotonic() + self.timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"token": self.token, "created_at": _utc_now()},
            sort_keys=True,
        ).encode("utf-8")

        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise IngestionLockError(
                        "another ingestion mutation currently owns the store lock"
                    )
                time.sleep(0.05)
                continue

            try:
                os.write(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self.acquired = True
            return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.acquired:
            return None
        try:
            lock_payload = _safe_json_read(self.path)
            if lock_payload.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        finally:
            self.acquired = False
        return None


class IngestionStore:
    def __init__(
        self,
        root: str | Path,
        source_registry: OfficialSourceRegistry,
        *,
        lock_timeout_seconds: float = 2.0,
    ):
        self.root = Path(root)
        self.source_registry = source_registry
        self.lock_timeout_seconds = lock_timeout_seconds
        self.objects_dir = self.root / "objects"
        self.manifests_dir = self.root / "manifests"
        self.active_dir = self.root / "active"
        self.events_dir = self.root / "activation_events"
        self.staging_dir = self.root / ".staging"
        self.lock_path = self.root / ".mutation.lock"

    def _mutation_lock(self) -> _MutationLock:
        return _MutationLock(self.lock_path, self.lock_timeout_seconds)

    @staticmethod
    def _validate_request(
        *,
        package_key: str,
        board: str,
        medium: str,
        standard: int,
        subject: str,
        academic_year: str,
        edition: str,
        source_id: str,
        ingestion_mode: str,
    ) -> dict[str, Any]:
        normalized = {
            "package_key": _clean(package_key, max_length=160),
            "board": _clean(board, max_length=20).upper(),
            "medium": _clean(medium, max_length=80),
            "standard": int(standard),
            "subject": _clean(subject, max_length=120),
            "academic_year": _clean(academic_year, max_length=80),
            "edition": _clean(edition, max_length=120),
            "source_id": _clean(source_id, max_length=120),
            "ingestion_mode": _clean(ingestion_mode, max_length=20).casefold(),
        }
        if not PACKAGE_KEY_RE.fullmatch(normalized["package_key"]):
            raise IngestionValidationError("invalid package_key")
        if normalized["board"] not in {"GSEB", "CBSE"}:
            raise IngestionValidationError("board must be GSEB or CBSE")
        if not normalized["medium"]:
            raise IngestionValidationError("medium is required")
        if normalized["standard"] not in range(1, 11):
            raise IngestionValidationError("standard must be between 1 and 10")
        if not normalized["subject"]:
            raise IngestionValidationError("subject is required")
        if not normalized["academic_year"]:
            raise IngestionValidationError("academic_year is required")
        if not normalized["edition"]:
            raise IngestionValidationError("edition is required")
        if not normalized["source_id"]:
            raise IngestionValidationError("source_id is required")
        if normalized["ingestion_mode"] not in INGESTION_MODES:
            raise IngestionValidationError(
                "ingestion_mode must be metadata or content"
            )
        return normalized

    def _authorize_source(
        self,
        *,
        source_id: str,
        board: str,
        standard: int,
        ingestion_mode: str,
    ) -> None:
        source = self.source_registry.get(source_id)
        if source is None:
            raise IngestionValidationError(f"unknown official source_id: {source_id}")
        if source.board != board:
            raise IngestionValidationError(
                "source board does not match package board"
            )
        if standard not in source.standards:
            raise IngestionValidationError(
                "source does not cover the requested standard"
            )
        if source.review_status not in {
            "approved_for_metadata",
            "approved_for_content",
        }:
            raise IngestionValidationError(
                "source is not approved even for metadata ingestion"
            )
        if ingestion_mode == "content" and not source.content_import_allowed:
            raise IngestionValidationError(
                "source is not approved for textbook-content ingestion"
            )

    @staticmethod
    def _artifact_from_path(path: Path, *, role: str) -> IngestionArtifact:
        if not path.is_file():
            raise IngestionValidationError(f"artifact file not found: {path}")
        name = path.name
        if name in {".", ".."} or Path(name).name != name:
            raise IngestionValidationError("artifact must resolve to a plain filename")
        digest, size = _sha256_file(path)
        media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        artifact = IngestionArtifact(
            name=name,
            role=_clean(role, max_length=80) or "source",
            media_type=media_type,
            sha256=digest,
            size_bytes=size,
        )
        artifact.validate()
        return artifact

    def build_manifest(
        self,
        *,
        package_key: str,
        board: str,
        medium: str,
        standard: int,
        subject: str,
        academic_year: str,
        edition: str,
        source_id: str,
        ingestion_mode: str,
        artifact_paths: Sequence[str | Path],
        artifact_role: str = "source",
    ) -> IngestionManifest:
        request = self._validate_request(
            package_key=package_key,
            board=board,
            medium=medium,
            standard=standard,
            subject=subject,
            academic_year=academic_year,
            edition=edition,
            source_id=source_id,
            ingestion_mode=ingestion_mode,
        )
        self._authorize_source(
            source_id=request["source_id"],
            board=request["board"],
            standard=request["standard"],
            ingestion_mode=request["ingestion_mode"],
        )
        if not artifact_paths:
            raise IngestionValidationError("at least one artifact path is required")

        resolved_paths = [Path(item).resolve(strict=True) for item in artifact_paths]
        artifacts = tuple(
            self._artifact_from_path(path, role=artifact_role)
            for path in resolved_paths
        )
        names = [artifact.name.casefold() for artifact in artifacts]
        if len(names) != len(set(names)):
            raise IngestionValidationError("artifact filenames must be unique")

        previous_revision_id = ""
        active = self.get_active(request["package_key"])
        if active is not None:
            previous_revision_id = active.revision_id

        provisional = IngestionManifest(
            schema_version=1,
            revision_id="0" * 64,
            package_key=request["package_key"],
            board=request["board"],
            medium=request["medium"],
            standard=request["standard"],
            subject=request["subject"],
            academic_year=request["academic_year"],
            edition=request["edition"],
            source_id=request["source_id"],
            ingestion_mode=request["ingestion_mode"],
            artifacts=artifacts,
            previous_revision_id=previous_revision_id,
            created_at=_utc_now(),
        )
        revision_id = provisional.calculate_revision_id()
        manifest = IngestionManifest(
            **{
                **provisional.__dict__,
                "revision_id": revision_id,
            }
        )
        manifest.validate()
        return manifest

    def _manifest_path(self, revision_id: str) -> Path:
        normalized = _clean(revision_id, max_length=64).casefold()
        if not SHA256_RE.fullmatch(normalized):
            raise IngestionValidationError("invalid revision_id")
        return self.manifests_dir / f"{normalized}.json"

    def _object_path(self, digest: str) -> Path:
        normalized = _clean(digest, max_length=64).casefold()
        if not SHA256_RE.fullmatch(normalized):
            raise IngestionValidationError("invalid object checksum")
        return self.objects_dir / normalized[:2] / normalized

    def _active_path(self, package_key: str) -> Path:
        normalized = _clean(package_key, max_length=160)
        if not PACKAGE_KEY_RE.fullmatch(normalized):
            raise IngestionValidationError("invalid package_key")
        return self.active_dir / f"{normalized}.json"

    def load_manifest(self, revision_id: str) -> IngestionManifest:
        path = self._manifest_path(revision_id)
        if not path.is_file():
            raise IntegrityError(f"manifest not found: {revision_id}")
        return IngestionManifest.from_dict(_safe_json_read(path))

    def get_active(self, package_key: str) -> IngestionManifest | None:
        pointer_path = self._active_path(package_key)
        if not pointer_path.exists():
            return None
        pointer = _safe_json_read(pointer_path)
        revision_id = _clean(pointer.get("revision_id"), max_length=64).casefold()
        manifest = self.load_manifest(revision_id)
        if manifest.package_key != package_key:
            raise IntegrityError("active pointer package mismatch")
        return manifest

    def _find_same_edition(
        self,
        package_key: str,
        edition: str,
    ) -> IngestionManifest | None:
        if not self.manifests_dir.exists():
            return None
        for path in self.manifests_dir.glob("*.json"):
            manifest = IngestionManifest.from_dict(_safe_json_read(path))
            if (
                manifest.package_key == package_key
                and manifest.edition.casefold() == edition.casefold()
            ):
                return manifest
        return None

    def _copy_object(self, source_path: Path, artifact: IngestionArtifact) -> None:
        destination = self._object_path(artifact.sha256)
        if destination.exists():
            digest, size = _sha256_file(destination)
            if digest != artifact.sha256 or size != artifact.size_bytes:
                raise IntegrityError(
                    f"stored object checksum mismatch: {artifact.sha256}"
                )
            return

        destination.parent.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.staging_dir / f"{uuid.uuid4().hex}.object"
        try:
            with source_path.open("rb") as source, temp_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            digest, size = _sha256_file(temp_path)
            if digest != artifact.sha256 or size != artifact.size_bytes:
                raise IntegrityError(
                    f"artifact changed during ingestion: {source_path.name}"
                )
            try:
                os.replace(temp_path, destination)
            except OSError:
                if not destination.exists():
                    raise
                digest, size = _sha256_file(destination)
                if digest != artifact.sha256 or size != artifact.size_bytes:
                    raise IntegrityError(
                        f"concurrent object checksum mismatch: {artifact.sha256}"
                    )
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_manifest_once(self, manifest: IngestionManifest) -> None:
        path = self._manifest_path(manifest.revision_id)
        payload = manifest.to_dict()
        if path.exists():
            existing = IngestionManifest.from_dict(_safe_json_read(path))
            if existing.to_dict() != payload:
                raise IntegrityError(
                    "immutable manifest path already contains different content"
                )
            raise DuplicateIngestionError(
                f"revision already exists: {manifest.revision_id}"
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.staging_dir / f"{uuid.uuid4().hex}.manifest"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        try:
            with temp_path.open("wb") as handle:
                handle.write(_canonical_json(payload) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _activate(
        self,
        manifest: IngestionManifest,
        *,
        reason: str,
        from_revision_id: str = "",
    ) -> None:
        self.verify_revision(manifest.revision_id)
        pointer = {
            "schema_version": 1,
            "package_key": manifest.package_key,
            "revision_id": manifest.revision_id,
            "activated_at": _utc_now(),
            "reason": _clean(reason, max_length=160),
            "from_revision_id": _clean(from_revision_id, max_length=64).casefold(),
        }
        _atomic_write_json(self._active_path(manifest.package_key), pointer)

        event_dir = self.events_dir / manifest.package_key
        event_name = (
            f"{time.time_ns():020d}-{uuid.uuid4().hex}-"
            f"{manifest.revision_id}.json"
        )
        _atomic_write_json(event_dir / event_name, pointer)

    def ingest(
        self,
        *,
        package_key: str,
        board: str,
        medium: str,
        standard: int,
        subject: str,
        academic_year: str,
        edition: str,
        source_id: str,
        ingestion_mode: str,
        artifact_paths: Sequence[str | Path],
        artifact_role: str = "source",
    ) -> IngestionManifest:
        resolved_paths = [Path(item).resolve(strict=True) for item in artifact_paths]
        with self._mutation_lock():
            manifest = self.build_manifest(
                package_key=package_key,
                board=board,
                medium=medium,
                standard=standard,
                subject=subject,
                academic_year=academic_year,
                edition=edition,
                source_id=source_id,
                ingestion_mode=ingestion_mode,
                artifact_paths=resolved_paths,
                artifact_role=artifact_role,
            )

            manifest_path = self._manifest_path(manifest.revision_id)
            if manifest_path.exists():
                existing = IngestionManifest.from_dict(
                    _safe_json_read(manifest_path)
                )
                if existing.identity_payload() == manifest.identity_payload():
                    raise DuplicateIngestionError(
                        f"revision already exists: {manifest.revision_id}"
                    )
                raise IntegrityError(
                    "immutable manifest ID collision or stored manifest corruption"
                )

            same_edition = self._find_same_edition(
                manifest.package_key,
                manifest.edition,
            )
            if (
                same_edition is not None
                and same_edition.revision_id != manifest.revision_id
            ):
                raise EditionConflictError(
                    "same package edition already exists with different content"
                )

            for path, artifact in zip(resolved_paths, manifest.artifacts):
                self._copy_object(path, artifact)

            self._write_manifest_once(manifest)
            self.verify_revision(manifest.revision_id)

            active = self.get_active(manifest.package_key)
            from_revision = active.revision_id if active is not None else ""
            self._activate(
                manifest,
                reason="ingestion",
                from_revision_id=from_revision,
            )
            return manifest

    def verify_revision(self, revision_id: str) -> IngestionManifest:
        manifest = self.load_manifest(revision_id)
        for artifact in manifest.artifacts:
            object_path = self._object_path(artifact.sha256)
            if not object_path.is_file():
                raise IntegrityError(
                    f"stored object missing: {artifact.sha256}"
                )
            digest, size = _sha256_file(object_path)
            if digest != artifact.sha256 or size != artifact.size_bytes:
                raise IntegrityError(
                    f"stored object failed checksum verification: {artifact.name}"
                )
        return manifest

    def rollback(
        self,
        package_key: str,
        *,
        target_revision_id: str | None = None,
    ) -> IngestionManifest:
        with self._mutation_lock():
            active = self.get_active(package_key)
            if active is None:
                raise RollbackError("package has no active revision")

            target_id = _clean(target_revision_id, max_length=64).casefold()
            if not target_id:
                target_id = active.previous_revision_id
            if not target_id:
                raise RollbackError("active revision has no previous revision")

            target = self.verify_revision(target_id)
            if target.package_key != package_key:
                raise RollbackError(
                    "rollback target belongs to a different package"
                )
            if target.revision_id == active.revision_id:
                raise RollbackError("rollback target is already active")

            self._activate(
                target,
                reason="rollback",
                from_revision_id=active.revision_id,
            )
            return target

    def activation_events(self, package_key: str) -> tuple[dict[str, Any], ...]:
        normalized_path = self._active_path(package_key)
        del normalized_path
        event_dir = self.events_dir / package_key
        if not event_dir.exists():
            return ()
        return tuple(
            _safe_json_read(path)
            for path in sorted(event_dir.glob("*.json"))
        )
