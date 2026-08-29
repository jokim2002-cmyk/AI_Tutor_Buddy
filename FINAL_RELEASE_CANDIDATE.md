# Phase 10 & Phase 11 — Release Candidate & Truthful Acceptance Evidence Specification

> [!NOTE]
> **Historical Record & Current Status:**
> Files present in `release/` (e.g. `GyanVerse_Academy_v1.0.0_RC.zip` and associated JSON manifests) represent **historical backend-only checkpoint evidence** from initial Phase 10 development on commit `cc385836...` (193 tests).
> Current release candidate evaluation for **v1.1.0** (Classes 1–10, GSEB/CBSE) remains **PENDING** and **NOT APPROVED**.

## Release Gate Framework

Source code validation and automated unit test passes do **NOT** equal packaged-build or physical-device acceptance.

The current release auditor enforces the following explicit gates:

1. **Project Version Gate:** Dynamically resolved from `pyproject.toml` (`v1.1.0`).
2. **Automated Regression Gate:** Requires real regression execution passing all unit tests (`tests_passed=True`, `test_count > 0`).
3. **Runtime Dependency Gate:** All production dependencies (`flet`, `google-genai`, `flet-audio-recorder`, etc.) must import without error.
4. **Startup Smoke Gate:** Requires explicit verification evidence (default: `PENDING`).
5. **Documentation Review Gate:** Requires explicit review evidence (default: `PENDING`).
6. **Windows Packaged Build Acceptance Gate:** Requires a valid `.exe` artifact with matching SHA-256 (default: `PENDING`). A documentation-only `.zip` is rejected.
7. **Android Packaged Build Acceptance Gate:** Requires a valid `.apk` artifact with matching SHA-256 (default: `PENDING`). A documentation-only `.zip` is rejected.
8. **Physical Windows Device Acceptance Gate:** Desktop platform acceptance evidence (default: `PENDING` / `NOT_APPLICABLE`).
9. **Physical Android Device Acceptance Gate:** Hardware phone acceptance evidence (default: `PENDING`).
10. **Curriculum Readiness Gate:** Requires official verified textbook dataset packages installed (default: `PENDING`). Code repository class existence alone does not satisfy curriculum readiness.

## Approval Rule

Final release decision evaluates to **APPROVED** if and only if **EVERY** mandatory gate is **PASS**. Any mandatory gate marked `PENDING` or `FAIL` prevents release candidate approval and halts final release bundle generation.
