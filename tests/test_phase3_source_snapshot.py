from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from syllabus_ingestion import EditionConflictError, IngestionStore
from syllabus_source_registry import OfficialSourceRegistry
from syllabus_source_snapshot import (
    MetadataProbeResult,
    OfficialSourceSnapshot,
    OfficialSourceSnapshotPipeline,
    SnapshotIntegrityError,
    SnapshotRequest,
    SnapshotTransportError,
    SnapshotValidationError,
)


INVENTORY = {
    "schema_version": 1,
    "sources": [
        {
            "source_id": "ncert-textbook-catalog",
            "board": "CBSE",
            "authority": "National Council of Educational Research and Training",
            "source_url": "https://ncert.nic.in/textbook.php",
            "standards": list(range(1, 11)),
            "mediums": ["English", "Hindi"],
            "content_scope": "official textbook catalog",
            "academic_year": "current",
            "review_status": "approved_for_metadata",
            "reuse_status": "verification_required",
            "license_reference": "",
            "sha256_required": True,
        },
        {
            "source_id": "gseb-discovered",
            "board": "GSEB",
            "authority": "GSEB",
            "source_url": "https://website.gseb.org/",
            "standards": [9, 10],
            "mediums": ["Gujarati"],
            "content_scope": "discovery only",
            "academic_year": "2026-27",
            "review_status": "discovered",
            "reuse_status": "verification_required",
            "license_reference": "",
            "sha256_required": True,
        },
    ],
}


class FakeTransport:
    def __init__(self, result: MetadataProbeResult):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def probe(self, url: str, *, allowed_host: str) -> MetadataProbeResult:
        self.calls.append((url, allowed_host))
        return self.result


class Phase3SourceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = OfficialSourceRegistry.from_payload(INVENTORY)
        self.request = SnapshotRequest(
            package_key="cbse-en-7-mathematics-source",
            board="CBSE",
            medium="English",
            standard=7,
            subject="Mathematics",
            academic_year="2026-27",
            edition="snapshot-r1",
            source_id="ncert-textbook-catalog",
            target_url="https://ncert.nic.in/textbook.php",
        )
        self.probe = MetadataProbeResult(
            requested_url="https://ncert.nic.in/textbook.php",
            final_url="https://ncert.nic.in/textbook.php",
            method="HEAD",
            status_code=200,
            headers={
                "Content-Type": "text/html; charset=UTF-8",
                "ETag": '"abc123"',
                "Last-Modified": "Thu, 06 Aug 2026 10:00:00 GMT",
                "Set-Cookie": "secret=must-not-be-recorded",
                "X-Internal": "must-not-be-recorded",
            },
            redirect_chain=(),
            body_bytes_read=0,
        )

    def pipeline(self, result: MetadataProbeResult | None = None):
        transport = FakeTransport(result or self.probe)
        pipeline = OfficialSourceSnapshotPipeline(
            self.registry,
            transport=transport,
            clock=lambda: "2026-08-07T00:30:00Z",
        )
        return pipeline, transport

    def test_preview_is_network_free_and_explicitly_blocks_body_capture(self) -> None:
        pipeline, transport = self.pipeline()
        plan = pipeline.preview(self.request)
        self.assertEqual(transport.calls, [])
        self.assertFalse(plan.body_capture_allowed)
        self.assertEqual(plan.preferred_method, "HEAD")
        self.assertEqual(plan.fallback_method, "GET_RANGE_HEADERS_ONLY")
        self.assertFalse(plan.to_dict()["network_performed"])

    def test_preview_normalizes_official_url(self) -> None:
        pipeline, _ = self.pipeline()
        plan = pipeline.preview(
            replace(self.request, target_url="https://NCERT.NIC.IN")
        )
        self.assertEqual(plan.request.target_url, "https://ncert.nic.in/")

    def test_unknown_source_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(replace(self.request, source_id="unknown"))

    def test_board_mismatch_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(replace(self.request, board="GSEB"))

    def test_uncovered_standard_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        request = SnapshotRequest(
            package_key="gseb-gu-7-math-source",
            board="GSEB",
            medium="Gujarati",
            standard=7,
            subject="Mathematics",
            academic_year="2026-27",
            edition="snapshot-r1",
            source_id="gseb-discovered",
            target_url="https://website.gseb.org/",
        )
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(request)

    def test_discovered_but_unapproved_source_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        request = SnapshotRequest(
            package_key="gseb-gu-9-math-source",
            board="GSEB",
            medium="Gujarati",
            standard=9,
            subject="Mathematics",
            academic_year="2026-27",
            edition="snapshot-r1",
            source_id="gseb-discovered",
            target_url="https://website.gseb.org/",
        )
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(request)

    def test_http_target_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(
                replace(self.request, target_url="http://ncert.nic.in/textbook.php")
            )

    def test_credentials_in_target_are_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(
                replace(
                    self.request,
                    target_url="https://user:pass@ncert.nic.in/textbook.php",
                )
            )

    def test_fragment_in_target_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(
                replace(
                    self.request,
                    target_url="https://ncert.nic.in/textbook.php#chapter",
                )
            )

    def test_cross_host_target_is_rejected(self) -> None:
        pipeline, _ = self.pipeline()
        with self.assertRaises(SnapshotValidationError):
            pipeline.preview(
                replace(self.request, target_url="https://example.com/textbook.php")
            )

    def test_capture_records_only_safe_headers(self) -> None:
        pipeline, transport = self.pipeline()
        snapshot = pipeline.capture(pipeline.preview(self.request))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(
            snapshot.headers,
            {
                "content-type": "text/html; charset=UTF-8",
                "etag": '"abc123"',
                "last-modified": "Thu, 06 Aug 2026 10:00:00 GMT",
            },
        )
        self.assertNotIn("set-cookie", snapshot.headers)
        self.assertEqual(snapshot.body_bytes_read, 0)

    def test_capture_rejects_transport_that_read_body_bytes(self) -> None:
        pipeline, _ = self.pipeline(replace(self.probe, body_bytes_read=1))
        with self.assertRaises(SnapshotIntegrityError):
            pipeline.capture(pipeline.preview(self.request))

    def test_capture_rejects_failure_status(self) -> None:
        pipeline, _ = self.pipeline(replace(self.probe, status_code=404))
        with self.assertRaises(SnapshotTransportError):
            pipeline.capture(pipeline.preview(self.request))

    def test_capture_rejects_cross_host_final_url(self) -> None:
        pipeline, _ = self.pipeline(
            replace(self.probe, final_url="https://example.com/textbook.php")
        )
        with self.assertRaises(SnapshotIntegrityError):
            pipeline.capture(pipeline.preview(self.request))

    def test_snapshot_id_detects_mutation(self) -> None:
        pipeline, _ = self.pipeline()
        snapshot = pipeline.capture(pipeline.preview(self.request))
        payload = snapshot.to_dict()
        payload["status_code"] = 204
        with self.assertRaises(SnapshotIntegrityError):
            OfficialSourceSnapshot.from_dict(payload)

    def test_snapshot_write_and_load_round_trip(self) -> None:
        pipeline, _ = self.pipeline()
        snapshot = pipeline.capture(pipeline.preview(self.request))
        with tempfile.TemporaryDirectory() as temporary:
            path = pipeline.write_snapshot(
                snapshot,
                Path(temporary) / "source-snapshot.json",
            )
            loaded = pipeline.load_snapshot(path)
        self.assertEqual(loaded, snapshot)

    def test_capture_and_ingest_creates_verified_metadata_manifest(self) -> None:
        pipeline, _ = self.pipeline()
        with tempfile.TemporaryDirectory() as temporary:
            store = IngestionStore(Path(temporary) / "store", self.registry)
            result = pipeline.capture_and_ingest(store, self.request)
            active = store.get_active(self.request.package_key)
            self.assertIsNotNone(active)
            self.assertEqual(active.revision_id, result.manifest.revision_id)
            self.assertEqual(result.manifest.ingestion_mode, "metadata")
            self.assertEqual(
                result.manifest.artifacts[0].role,
                "official_source_snapshot",
            )
            self.assertTrue(
                result.manifest.artifacts[0].name.startswith(
                    "official-source-snapshot-"
                )
            )
            store.verify_revision(result.manifest.revision_id)

    def test_same_edition_changed_snapshot_is_rejected(self) -> None:
        first_pipeline, _ = self.pipeline()
        changed_probe = replace(
            self.probe,
            headers={"Content-Type": "text/html", "ETag": '"changed"'},
        )
        second_pipeline, _ = self.pipeline(changed_probe)
        with tempfile.TemporaryDirectory() as temporary:
            store = IngestionStore(Path(temporary) / "store", self.registry)
            first_pipeline.capture_and_ingest(store, self.request)
            with self.assertRaises(EditionConflictError):
                second_pipeline.capture_and_ingest(store, self.request)


if __name__ == "__main__":
    unittest.main()
