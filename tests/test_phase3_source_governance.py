from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from syllabus_source_registry import (
    ALLOWED_OFFICIAL_HOSTS,
    OfficialSourceRecord,
    OfficialSourceRegistry,
    SourceGovernanceError,
)


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "syllabus" / "official_source_inventory.json"


class Phase3SourceGovernanceTests(unittest.TestCase):
    def test_checked_in_inventory_loads(self) -> None:
        registry = OfficialSourceRegistry.load(INVENTORY)
        self.assertEqual(len(registry.records), 4)
        self.assertEqual(len(registry.for_board("GSEB")), 2)
        self.assertEqual(len(registry.for_board("CBSE")), 2)

    def test_inventory_has_no_content_approved_sources_yet(self) -> None:
        registry = OfficialSourceRegistry.load(INVENTORY)
        self.assertEqual(registry.approved_for_content(), ())

    def test_matrix_has_both_boards_and_classes_one_to_ten(self) -> None:
        registry = OfficialSourceRegistry.load(INVENTORY)
        matrix = registry.coverage_matrix()
        self.assertEqual(set(matrix), {"CBSE", "GSEB"})
        self.assertEqual(set(matrix["CBSE"]), set(range(1, 11)))
        self.assertEqual(set(matrix["GSEB"]), set(range(1, 11)))
        for standard in range(1, 11):
            self.assertTrue(matrix["CBSE"][standard])
            self.assertTrue(matrix["GSEB"][standard])

    def test_only_allowlisted_official_hosts_are_present(self) -> None:
        registry = OfficialSourceRegistry.load(INVENTORY)
        for record in registry.records:
            self.assertIn(record.host, ALLOWED_OFFICIAL_HOSTS[record.board])

    def test_third_party_mirror_is_rejected(self) -> None:
        payload = {
            "source_id": "bad-mirror",
            "board": "GSEB",
            "authority": "Unofficial mirror",
            "source_url": "https://example.com/textbook.pdf",
            "standards": [7],
            "mediums": ["Gujarati"],
            "content_scope": "textbook",
            "academic_year": "2026-27",
            "review_status": "approved_for_metadata",
            "reuse_status": "metadata_only",
        }
        with self.assertRaises(SourceGovernanceError):
            OfficialSourceRecord.from_dict(payload)

    def test_http_source_is_rejected(self) -> None:
        payload = {
            "source_id": "insecure",
            "board": "CBSE",
            "authority": "NCERT",
            "source_url": "http://ncert.nic.in/textbook.php",
            "standards": [7],
            "mediums": ["English"],
            "content_scope": "textbook catalog",
            "academic_year": "current",
            "review_status": "approved_for_metadata",
            "reuse_status": "metadata_only",
        }
        with self.assertRaises(SourceGovernanceError):
            OfficialSourceRecord.from_dict(payload)

    def test_content_approval_requires_verified_reuse_rights(self) -> None:
        payload = {
            "source_id": "unlicensed-content",
            "board": "CBSE",
            "authority": "NCERT",
            "source_url": "https://ncert.nic.in/textbook.php",
            "standards": [7],
            "mediums": ["English"],
            "content_scope": "textbook content",
            "academic_year": "current",
            "review_status": "approved_for_content",
            "reuse_status": "verification_required",
            "license_reference": "",
            "sha256_required": True,
        }
        with self.assertRaises(SourceGovernanceError):
            OfficialSourceRecord.from_dict(payload)

    def test_content_approval_requires_sha256(self) -> None:
        payload = {
            "source_id": "licensed-without-hash",
            "board": "CBSE",
            "authority": "NCERT",
            "source_url": "https://ncert.nic.in/textbook.php",
            "standards": [7],
            "mediums": ["English"],
            "content_scope": "textbook content",
            "academic_year": "current",
            "review_status": "approved_for_content",
            "reuse_status": "permission_granted",
            "license_reference": "Written permission reference",
            "sha256_required": False,
        }
        with self.assertRaises(SourceGovernanceError):
            OfficialSourceRecord.from_dict(payload)

    def test_valid_permission_record_allows_content_import(self) -> None:
        payload = {
            "source_id": "licensed-content",
            "board": "CBSE",
            "authority": "NCERT",
            "source_url": "https://ncert.nic.in/textbook.php",
            "standards": [7],
            "mediums": ["English"],
            "content_scope": "approved excerpt package",
            "academic_year": "current",
            "review_status": "approved_for_content",
            "reuse_status": "permission_granted",
            "license_reference": "Permission letter GOV-123",
            "sha256_required": True,
        }
        record = OfficialSourceRecord.from_dict(payload)
        self.assertTrue(record.content_import_allowed)

    def test_duplicate_source_ids_are_rejected(self) -> None:
        payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
        payload["sources"].append(dict(payload["sources"][0]))
        with self.assertRaises(SourceGovernanceError):
            OfficialSourceRegistry.from_payload(payload)

    def test_unsupported_standard_is_rejected(self) -> None:
        payload = {
            "source_id": "bad-standard",
            "board": "GSEB",
            "authority": "GSEB",
            "source_url": "https://website.gseb.org/",
            "standards": [11],
            "mediums": ["Gujarati"],
            "content_scope": "curriculum",
            "academic_year": "2026-27",
            "review_status": "approved_for_metadata",
            "reuse_status": "metadata_only",
        }
        with self.assertRaises(SourceGovernanceError):
            OfficialSourceRecord.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
