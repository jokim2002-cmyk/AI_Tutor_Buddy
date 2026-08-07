from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from syllabus_ingestion import IngestionManifest, IngestionStore
from syllabus_source_registry import OfficialSourceRecord, OfficialSourceRegistry


class SourceSnapshotError(RuntimeError):
    """Base error for official-source metadata snapshots."""


class SnapshotValidationError(SourceSnapshotError):
    """Raised when a snapshot request violates governance rules."""


class SnapshotTransportError(SourceSnapshotError):
    """Raised when remote metadata cannot be probed safely."""


class SnapshotIntegrityError(SourceSnapshotError):
    """Raised when snapshot evidence is missing, malformed, or mutated."""


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_METHODS = {"HEAD", "GET_RANGE_HEADERS_ONLY"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_HEADER_NAMES = (
    "accept-ranges",
    "cache-control",
    "content-language",
    "content-length",
    "content-type",
    "date",
    "etag",
    "expires",
    "last-modified",
    "location",
)


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


def _normalize_https_url(value: object) -> str:
    raw = _clean(value, max_length=2_000)
    parsed = urlparse(raw)
    if parsed.scheme.casefold() != "https":
        raise SnapshotValidationError("source snapshot URL must use HTTPS")
    if not parsed.hostname:
        raise SnapshotValidationError("source snapshot URL must include a host")
    if parsed.username or parsed.password:
        raise SnapshotValidationError("source snapshot URL cannot contain credentials")
    if parsed.port not in {None, 443}:
        raise SnapshotValidationError("source snapshot URL must use the default HTTPS port")
    if parsed.fragment:
        raise SnapshotValidationError("source snapshot URL cannot contain a fragment")
    host = parsed.hostname.casefold()
    netloc = host
    normalized = parsed._replace(
        scheme="https",
        netloc=netloc,
        path=parsed.path or "/",
        fragment="",
    )
    return urlunparse(normalized)


def _safe_headers(headers: Mapping[str, object]) -> dict[str, str]:
    normalized = {str(key).casefold(): value for key, value in headers.items()}
    result: dict[str, str] = {}
    for name in SAFE_HEADER_NAMES:
        if name not in normalized:
            continue
        value = _clean(normalized[name], max_length=1_000)
        if value:
            result[name] = value
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(_canonical_json(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class SnapshotRequest:
    package_key: str
    board: str
    medium: str
    standard: int
    subject: str
    academic_year: str
    edition: str
    source_id: str
    target_url: str


@dataclass(frozen=True)
class SourceSnapshotPlan:
    request: SnapshotRequest
    authority: str
    registered_source_url: str
    allowed_host: str
    preferred_method: str = "HEAD"
    fallback_method: str = "GET_RANGE_HEADERS_ONLY"
    body_capture_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "request": asdict(self.request),
            "authority": self.authority,
            "registered_source_url": self.registered_source_url,
            "allowed_host": self.allowed_host,
            "preferred_method": self.preferred_method,
            "fallback_method": self.fallback_method,
            "body_capture_allowed": self.body_capture_allowed,
            "network_performed": False,
        }


@dataclass(frozen=True)
class MetadataProbeResult:
    requested_url: str
    final_url: str
    method: str
    status_code: int
    headers: Mapping[str, str]
    redirect_chain: tuple[str, ...] = ()
    body_bytes_read: int = 0


class MetadataTransport(Protocol):
    def probe(self, url: str, *, allowed_host: str) -> MetadataProbeResult:
        ...


class _SameHostRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_host: str, redirect_chain: list[str], max_redirects: int):
        super().__init__()
        self.allowed_host = allowed_host.casefold()
        self.redirect_chain = redirect_chain
        self.max_redirects = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        normalized = _normalize_https_url(newurl)
        host = (urlparse(normalized).hostname or "").casefold()
        if host != self.allowed_host:
            raise SnapshotTransportError("cross-host redirect is not allowed")
        if len(self.redirect_chain) >= self.max_redirects:
            raise SnapshotTransportError("too many redirects while probing source metadata")
        self.redirect_chain.append(normalized)
        return super().redirect_request(req, fp, code, msg, headers, normalized)


class HttpMetadataTransport:
    """Probe response metadata without reading or storing response bodies."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 12.0,
        max_redirects: int = 5,
        user_agent: str = "GyanVerse-SourceSnapshot/1.0",
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self.timeout_seconds = float(timeout_seconds)
        self.max_redirects = int(max_redirects)
        self.user_agent = _clean(user_agent, max_length=200)

    def _request(
        self,
        url: str,
        *,
        allowed_host: str,
        method: str,
        range_headers_only: bool,
    ) -> MetadataProbeResult:
        redirect_chain: list[str] = []
        redirect_handler = _SameHostRedirectHandler(
            allowed_host,
            redirect_chain,
            self.max_redirects,
        )
        opener = build_opener(redirect_handler)
        headers = {
            "Accept": "*/*",
            "User-Agent": self.user_agent,
        }
        if range_headers_only:
            headers["Range"] = "bytes=0-0"
        request = Request(url, headers=headers, method=method)
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                final_url = _normalize_https_url(response.geturl())
                final_host = (urlparse(final_url).hostname or "").casefold()
                if final_host != allowed_host.casefold():
                    raise SnapshotTransportError("final response host is not allowlisted")
                status = int(response.getcode())
                return MetadataProbeResult(
                    requested_url=url,
                    final_url=final_url,
                    method=(
                        "GET_RANGE_HEADERS_ONLY" if range_headers_only else "HEAD"
                    ),
                    status_code=status,
                    headers=_safe_headers(dict(response.headers.items())),
                    redirect_chain=tuple(redirect_chain),
                    body_bytes_read=0,
                )
        except SnapshotTransportError:
            raise
        except HTTPError as exc:
            if method == "HEAD" and exc.code in {405, 501}:
                raise
            raise SnapshotTransportError(
                f"official source metadata probe returned HTTP {exc.code}"
            ) from exc
        except (URLError, OSError, ValueError) as exc:
            raise SnapshotTransportError(
                f"official source metadata probe failed: {exc}"
            ) from exc

    def probe(self, url: str, *, allowed_host: str) -> MetadataProbeResult:
        normalized_url = _normalize_https_url(url)
        normalized_host = _clean(allowed_host, max_length=255).casefold()
        if (urlparse(normalized_url).hostname or "").casefold() != normalized_host:
            raise SnapshotValidationError("target URL host does not match allowed host")
        try:
            return self._request(
                normalized_url,
                allowed_host=normalized_host,
                method="HEAD",
                range_headers_only=False,
            )
        except HTTPError as exc:
            if exc.code not in {405, 501}:
                raise
            return self._request(
                normalized_url,
                allowed_host=normalized_host,
                method="GET",
                range_headers_only=True,
            )


@dataclass(frozen=True)
class OfficialSourceSnapshot:
    schema_version: int
    snapshot_id: str
    source_id: str
    authority: str
    registered_source_url: str
    requested_url: str
    final_url: str
    http_method: str
    status_code: int
    headers: Mapping[str, str]
    redirect_chain: tuple[str, ...]
    acquired_at: str
    body_bytes_read: int
    source_review_status: str
    source_reuse_status: str

    def evidence_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "authority": self.authority,
            "registered_source_url": self.registered_source_url,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "http_method": self.http_method,
            "status_code": self.status_code,
            "headers": dict(sorted(self.headers.items())),
            "redirect_chain": list(self.redirect_chain),
            "acquired_at": self.acquired_at,
            "body_bytes_read": self.body_bytes_read,
            "source_review_status": self.source_review_status,
            "source_reuse_status": self.source_reuse_status,
        }

    def calculate_snapshot_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.evidence_payload()))

    def validate(self) -> None:
        if self.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise SnapshotIntegrityError("snapshot schema_version must be 1")
        if not SHA256_RE.fullmatch(self.snapshot_id):
            raise SnapshotIntegrityError("snapshot_id must be a SHA-256 digest")
        if self.snapshot_id != self.calculate_snapshot_id():
            raise SnapshotIntegrityError("snapshot_id does not match snapshot evidence")
        if self.http_method not in SNAPSHOT_METHODS:
            raise SnapshotIntegrityError("unsupported metadata probe method")
        if self.status_code < 200 or self.status_code >= 400:
            raise SnapshotIntegrityError("snapshot HTTP status must be successful")
        if self.body_bytes_read != 0:
            raise SnapshotIntegrityError("metadata snapshots cannot read response bodies")
        requested = _normalize_https_url(self.requested_url)
        final = _normalize_https_url(self.final_url)
        expected_host = (urlparse(requested).hostname or "").casefold()
        if (urlparse(final).hostname or "").casefold() != expected_host:
            raise SnapshotIntegrityError("snapshot final URL crossed official hosts")
        for item in self.redirect_chain:
            if (urlparse(_normalize_https_url(item)).hostname or "").casefold() != expected_host:
                raise SnapshotIntegrityError("snapshot redirect chain crossed official hosts")
        if dict(self.headers) != _safe_headers(self.headers):
            raise SnapshotIntegrityError("snapshot contains non-allowlisted HTTP headers")
        if not self.acquired_at.endswith("Z"):
            raise SnapshotIntegrityError("acquired_at must be a UTC timestamp")

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.evidence_payload(),
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OfficialSourceSnapshot":
        snapshot = cls(
            schema_version=int(payload.get("schema_version", 0)),
            snapshot_id=_clean(payload.get("snapshot_id"), max_length=64).casefold(),
            source_id=_clean(payload.get("source_id"), max_length=120),
            authority=_clean(payload.get("authority"), max_length=200),
            registered_source_url=_clean(
                payload.get("registered_source_url"), max_length=2_000
            ),
            requested_url=_clean(payload.get("requested_url"), max_length=2_000),
            final_url=_clean(payload.get("final_url"), max_length=2_000),
            http_method=_clean(payload.get("http_method"), max_length=40).upper(),
            status_code=int(payload.get("status_code", 0)),
            headers=_safe_headers(payload.get("headers", {})),
            redirect_chain=tuple(
                _clean(item, max_length=2_000)
                for item in payload.get("redirect_chain", [])
            ),
            acquired_at=_clean(payload.get("acquired_at"), max_length=80),
            body_bytes_read=int(payload.get("body_bytes_read", -1)),
            source_review_status=_clean(
                payload.get("source_review_status"), max_length=40
            ),
            source_reuse_status=_clean(
                payload.get("source_reuse_status"), max_length=40
            ),
        )
        snapshot.validate()
        return snapshot


@dataclass(frozen=True)
class SnapshotIngestionResult:
    snapshot: OfficialSourceSnapshot
    manifest: IngestionManifest


class OfficialSourceSnapshotPipeline:
    def __init__(
        self,
        registry: OfficialSourceRegistry,
        *,
        transport: MetadataTransport | None = None,
        clock: Callable[[], str] = _utc_now,
    ):
        self.registry = registry
        self.transport = transport or HttpMetadataTransport()
        self.clock = clock

    def _source_for_request(self, request: SnapshotRequest) -> OfficialSourceRecord:
        source = self.registry.get(_clean(request.source_id, max_length=120))
        if source is None:
            raise SnapshotValidationError(
                f"unknown official source_id: {request.source_id}"
            )
        board = _clean(request.board, max_length=20).upper()
        if source.board != board:
            raise SnapshotValidationError("source board does not match snapshot package")
        try:
            standard = int(request.standard)
        except (TypeError, ValueError) as exc:
            raise SnapshotValidationError("standard must be between 1 and 10") from exc
        if standard not in source.standards:
            raise SnapshotValidationError("source does not cover requested standard")
        if source.review_status not in {
            "approved_for_metadata",
            "approved_for_content",
        }:
            raise SnapshotValidationError(
                "source is not approved for metadata evidence"
            )
        return source

    def preview(self, request: SnapshotRequest) -> SourceSnapshotPlan:
        source = self._source_for_request(request)
        target_url = _normalize_https_url(request.target_url)
        target_host = (urlparse(target_url).hostname or "").casefold()
        if target_host != source.host:
            raise SnapshotValidationError(
                "snapshot target must stay on the registered official source host"
            )
        registered_url = _normalize_https_url(source.source_url)
        normalized_request = SnapshotRequest(
            package_key=_clean(request.package_key, max_length=160),
            board=source.board,
            medium=_clean(request.medium, max_length=80),
            standard=int(request.standard),
            subject=_clean(request.subject, max_length=120),
            academic_year=_clean(request.academic_year, max_length=80),
            edition=_clean(request.edition, max_length=120),
            source_id=source.source_id,
            target_url=target_url,
        )
        if not normalized_request.package_key:
            raise SnapshotValidationError("package_key is required")
        if not normalized_request.medium:
            raise SnapshotValidationError("medium is required")
        if not normalized_request.subject:
            raise SnapshotValidationError("subject is required")
        if not normalized_request.academic_year:
            raise SnapshotValidationError("academic_year is required")
        if not normalized_request.edition:
            raise SnapshotValidationError("edition is required")
        return SourceSnapshotPlan(
            request=normalized_request,
            authority=source.authority,
            registered_source_url=registered_url,
            allowed_host=source.host,
        )

    def capture(self, plan: SourceSnapshotPlan) -> OfficialSourceSnapshot:
        result = self.transport.probe(
            plan.request.target_url,
            allowed_host=plan.allowed_host,
        )
        if result.body_bytes_read != 0:
            raise SnapshotIntegrityError(
                "metadata transport read response body bytes"
            )
        if result.method not in SNAPSHOT_METHODS:
            raise SnapshotIntegrityError("metadata transport returned unsupported method")
        if result.status_code < 200 or result.status_code >= 400:
            raise SnapshotTransportError(
                f"official source metadata probe returned HTTP {result.status_code}"
            )
        requested_url = _normalize_https_url(result.requested_url)
        final_url = _normalize_https_url(result.final_url)
        for candidate in (requested_url, final_url, *result.redirect_chain):
            host = (urlparse(_normalize_https_url(candidate)).hostname or "").casefold()
            if host != plan.allowed_host:
                raise SnapshotIntegrityError(
                    "metadata probe escaped the registered official host"
                )
        acquired_at = _clean(self.clock(), max_length=80)
        provisional = OfficialSourceSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            snapshot_id="0" * 64,
            source_id=plan.request.source_id,
            authority=plan.authority,
            registered_source_url=plan.registered_source_url,
            requested_url=requested_url,
            final_url=final_url,
            http_method=result.method,
            status_code=result.status_code,
            headers=_safe_headers(result.headers),
            redirect_chain=tuple(result.redirect_chain),
            acquired_at=acquired_at,
            body_bytes_read=0,
            source_review_status=(
                self.registry.get(plan.request.source_id).review_status  # type: ignore[union-attr]
            ),
            source_reuse_status=(
                self.registry.get(plan.request.source_id).reuse_status  # type: ignore[union-attr]
            ),
        )
        snapshot = OfficialSourceSnapshot(
            **{
                **provisional.__dict__,
                "snapshot_id": provisional.calculate_snapshot_id(),
            }
        )
        snapshot.validate()
        return snapshot

    @staticmethod
    def write_snapshot(snapshot: OfficialSourceSnapshot, destination: str | Path) -> Path:
        snapshot.validate()
        path = Path(destination)
        if path.suffix.casefold() != ".json":
            raise SnapshotValidationError("snapshot destination must be a JSON file")
        _atomic_write_json(path, snapshot.to_dict())
        loaded = OfficialSourceSnapshot.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
        if loaded.snapshot_id != snapshot.snapshot_id:
            raise SnapshotIntegrityError("written snapshot failed read-back verification")
        return path

    @staticmethod
    def load_snapshot(path: str | Path) -> OfficialSourceSnapshot:
        source_path = Path(path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotIntegrityError(
                f"unable to read source snapshot: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SnapshotIntegrityError("source snapshot must be a JSON object")
        return OfficialSourceSnapshot.from_dict(payload)

    def capture_and_ingest(
        self,
        store: IngestionStore,
        request: SnapshotRequest,
    ) -> SnapshotIngestionResult:
        plan = self.preview(request)
        snapshot = self.capture(plan)
        filename = f"official-source-snapshot-{snapshot.snapshot_id}.json"
        with tempfile.TemporaryDirectory(prefix="gyanverse-source-snapshot-") as temp:
            artifact_path = self.write_snapshot(snapshot, Path(temp) / filename)
            manifest = store.ingest(
                package_key=plan.request.package_key,
                board=plan.request.board,
                medium=plan.request.medium,
                standard=plan.request.standard,
                subject=plan.request.subject,
                academic_year=plan.request.academic_year,
                edition=plan.request.edition,
                source_id=plan.request.source_id,
                ingestion_mode="metadata",
                artifact_paths=[artifact_path],
                artifact_role="official_source_snapshot",
            )
        if manifest.ingestion_mode != "metadata":
            raise SnapshotIntegrityError("snapshot bridge created non-metadata manifest")
        store.verify_revision(manifest.revision_id)
        return SnapshotIngestionResult(snapshot=snapshot, manifest=manifest)
