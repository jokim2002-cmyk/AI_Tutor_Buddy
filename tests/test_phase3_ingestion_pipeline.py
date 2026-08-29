from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from syllabus_ingestion import (
    DuplicateIngestionError,
    EditionConflictError,
    IngestionLockError,
    IngestionStore,
    IngestionValidationError,
    IntegrityError,
    RollbackError,
)
from syllabus_source_registry import OfficialSourceRegistry


def make_registry(*, content_allowed: bool = False) -> OfficialSourceRegistry:
    source = {
        "source_id": "ncert-catalog",
        "board": "CBSE",
        "authority": "National Council of Educational Research and Training",
        "source_url": "https://ncert.nic.in/textbook.php",
        "standards": [7, 8],
        "mediums": ["English"],
        "content_scope": "official textbook catalog",
        "academic_year": "2026-27",
        "review_status": (
            "approved_for_content"
            if content_allowed
            else "approved_for_metadata"
        ),
        "reuse_status": (
            "permission_granted"
            if content_allowed
            else "verification_required"
        ),
        "license_reference": (
            "Written permission TEST-123"
            if content_allowed
            else ""
        ),
        "sha256_required": True,
    }
    gseb = {
        "source_id": "gseb-board",
        "board": "GSEB",
        "authority": "Gujarat Secondary and Higher Secondary Education Board",
        "source_url": "https://website.gseb.org/",
        "standards": [7],
        "mediums": ["Gujarati"],
        "content_scope": "official board metadata",
        "academic_year": "2026-27",
        "review_status": "approved_for_metadata",
        "reuse_status": "metadata_only",
        "license_reference": "",
        "sha256_required": True,
    }
    return OfficialSourceRegistry.from_payload(
        {"schema_version": 1, "sources": [source, gseb]}
    )


class Phase3ImmutableIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = IngestionStore(
            self.root / "store",
            make_registry(),
            lock_timeout_seconds=0.05,
        )
        self.artifact = self.root / "metadata.json"
        self.artifact.write_text(
            '{"chapters":["Integers"]}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def ingest(
        self,
        *,
        edition: str = "2026-r1",
        artifact: Path | None = None,
        store: IngestionStore | None = None,
        package_key: str = "cbse-en-7-mathematics",
        board: str = "CBSE",
        source_id: str = "ncert-catalog",
        mode: str = "metadata",
    ):
        return (store or self.store).ingest(
            package_key=package_key,
            board=board,
            medium="English",
            standard=7,
            subject="Mathematics",
            academic_year="2026-27",
            edition=edition,
            source_id=source_id,
            ingestion_mode=mode,
            artifact_paths=[artifact or self.artifact],
            artifact_role="curriculum_metadata",
        )

    def test_metadata_ingestion_creates_immutable_manifest_and_active_pointer(self) -> None:
        manifest = self.ingest()
        self.assertEqual(self.store.get_active(manifest.package_key), manifest)
        self.assertTrue(
            (self.store.manifests_dir / f"{manifest.revision_id}.json").is_file()
        )
        object_path = (
            self.store.objects_dir
            / manifest.artifacts[0].sha256[:2]
            / manifest.artifacts[0].sha256
        )
        self.assertTrue(object_path.is_file())
        self.assertEqual(len(self.store.activation_events(manifest.package_key)), 1)

    def test_revision_id_is_deterministic_for_identical_identity_and_bytes(self) -> None:
        first = self.store.build_manifest(
            package_key="cbse-en-7-mathematics",
            board="CBSE",
            medium="English",
            standard=7,
            subject="Mathematics",
            academic_year="2026-27",
            edition="2026-r1",
            source_id="ncert-catalog",
            ingestion_mode="metadata",
            artifact_paths=[self.artifact],
        )
        second = self.store.build_manifest(
            package_key="cbse-en-7-mathematics",
            board="CBSE",
            medium="English",
            standard=7,
            subject="Mathematics",
            academic_year="2026-27",
            edition="2026-r1",
            source_id="ncert-catalog",
            ingestion_mode="metadata",
            artifact_paths=[self.artifact],
        )
        self.assertEqual(first.revision_id, second.revision_id)
        self.assertNotEqual(first.created_at, "")
        self.assertNotEqual(second.created_at, "")

    def test_exact_duplicate_revision_is_rejected(self) -> None:
        self.ingest()
        with self.assertRaises(DuplicateIngestionError):
            self.ingest()

    def test_same_edition_with_changed_bytes_is_rejected(self) -> None:
        self.ingest()
        changed = self.root / "changed.json"
        changed.write_text('{"chapters":["Fractions"]}\n', encoding="utf-8")
        with self.assertRaises(EditionConflictError):
            self.ingest(artifact=changed)

    def test_new_edition_creates_new_revision_and_tracks_previous(self) -> None:
        first = self.ingest()
        changed = self.root / "changed.json"
        changed.write_text('{"chapters":["Fractions"]}\n', encoding="utf-8")
        second = self.ingest(edition="2026-r2", artifact=changed)
        self.assertNotEqual(first.revision_id, second.revision_id)
        self.assertEqual(second.previous_revision_id, first.revision_id)
        self.assertEqual(
            self.store.get_active(second.package_key).revision_id,
            second.revision_id,
        )
        self.assertEqual(len(self.store.activation_events(second.package_key)), 2)

    def test_object_bytes_are_deduplicated_across_editions(self) -> None:
        first = self.ingest()
        second = self.ingest(edition="2026-r2")
        self.assertNotEqual(first.revision_id, second.revision_id)
        self.assertEqual(
            first.artifacts[0].sha256,
            second.artifacts[0].sha256,
        )
        objects = [
            path
            for path in self.store.objects_dir.rglob("*")
            if path.is_file()
        ]
        self.assertEqual(len(objects), 1)

    def test_checksum_tampering_is_detected(self) -> None:
        manifest = self.ingest()
        object_path = (
            self.store.objects_dir
            / manifest.artifacts[0].sha256[:2]
            / manifest.artifacts[0].sha256
        )
        object_path.write_bytes(b"tampered")
        with self.assertRaises(IntegrityError):
            self.store.verify_revision(manifest.revision_id)

    def test_rollback_restores_previous_without_deleting_new_revision(self) -> None:
        first = self.ingest()
        changed = self.root / "changed.json"
        changed.write_text('{"chapters":["Fractions"]}\n', encoding="utf-8")
        second = self.ingest(edition="2026-r2", artifact=changed)

        restored = self.store.rollback(second.package_key)

        self.assertEqual(restored.revision_id, first.revision_id)
        self.assertEqual(
            self.store.get_active(second.package_key).revision_id,
            first.revision_id,
        )
        self.assertTrue(
            (self.store.manifests_dir / f"{second.revision_id}.json").is_file()
        )
        self.assertEqual(len(self.store.activation_events(second.package_key)), 3)

    def test_rollback_rejects_revision_from_another_package(self) -> None:
        first = self.ingest()
        other_artifact = self.root / "other.json"
        other_artifact.write_text('{"chapters":["Heat"]}\n', encoding="utf-8")
        other = self.ingest(
            package_key="cbse-en-7-science",
            edition="2026-r1",
            artifact=other_artifact,
        )
        with self.assertRaises(RollbackError):
            self.store.rollback(
                first.package_key,
                target_revision_id=other.revision_id,
            )

    def test_first_revision_cannot_rollback_without_target(self) -> None:
        manifest = self.ingest()
        with self.assertRaises(RollbackError):
            self.store.rollback(manifest.package_key)

    def test_unapproved_content_ingestion_is_blocked(self) -> None:
        with self.assertRaises(IngestionValidationError):
            self.ingest(mode="content")

    def test_permission_approved_content_ingestion_succeeds(self) -> None:
        approved_store = IngestionStore(
            self.root / "approved-store",
            make_registry(content_allowed=True),
        )
        manifest = self.ingest(store=approved_store, mode="content")
        self.assertEqual(manifest.ingestion_mode, "content")
        self.assertEqual(
            approved_store.get_active(manifest.package_key).revision_id,
            manifest.revision_id,
        )

    def test_source_board_mismatch_is_rejected(self) -> None:
        with self.assertRaises(IngestionValidationError):
            self.ingest(board="GSEB")

    def test_invalid_package_key_is_rejected(self) -> None:
        with self.assertRaises(IngestionValidationError):
            self.ingest(package_key="../escape")

    def test_duplicate_artifact_filenames_are_rejected(self) -> None:
        first_dir = self.root / "one"
        second_dir = self.root / "two"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "metadata.json"
        second = second_dir / "metadata.json"
        first.write_text('{"a":1}', encoding="utf-8")
        second.write_text('{"a":2}', encoding="utf-8")

        with self.assertRaises(IngestionValidationError):
            self.store.build_manifest(
                package_key="cbse-en-7-mathematics",
                board="CBSE",
                medium="English",
                standard=7,
                subject="Mathematics",
                academic_year="2026-27",
                edition="2026-r1",
                source_id="ncert-catalog",
                ingestion_mode="metadata",
                artifact_paths=[first, second],
            )

    def test_existing_mutation_lock_blocks_changes_and_preserves_state(self) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.store.lock_path.write_text(
            json.dumps({"token": "other-process", "created_at": "now"}),
            encoding="utf-8",
        )
        with self.assertRaises(IngestionLockError):
            self.ingest()
        self.assertIsNone(
            self.store.get_active("cbse-en-7-mathematics")
        )
        self.assertFalse(self.store.manifests_dir.exists())


if __name__ == "__main__":
    unittest.main()
