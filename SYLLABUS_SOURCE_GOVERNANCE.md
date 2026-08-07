# GyanVerse Official Syllabus Source Governance

## Purpose

This policy controls how official GSEB and CBSE curriculum sources enter the GyanVerse local-first syllabus pipeline. It prevents third-party mirrors, stale editions, unverifiable files, and copyrighted textbook content from being silently treated as official production data.

## Current source map

GSEB source discovery uses the official Gujarat Secondary and Higher Secondary Education Board portal and the Gujarat State School Textbook Board portal. CBSE Class IX-X detailed curriculum discovery uses the CBSE Academics 2026-27 curriculum page. CBSE/NCERT textbook discovery for Classes I-X uses the official NCERT textbook catalog.

The source inventory is stored in `syllabus/official_source_inventory.json` and validated by `syllabus_source_registry.py`.

## Non-negotiable gates

1. Production sources must use HTTPS and an allowlisted official host.
2. Third-party textbook mirrors may help a human locate a source, but they cannot be recorded as production authorities.
3. `approved_for_metadata` allows titles, board, class, subject, edition, chapter names, source links, and provenance notes to be stored.
4. Textbook explanations, examples, exercises, solutions, or copied chapter text require `approved_for_content`.
5. `approved_for_content` requires one of:
   - explicit written permission,
   - a verified open license,
   - verified public-domain status.
6. Every approved content file requires a SHA-256 fingerprint, acquisition date, academic year, edition/revision, and source record ID.
7. Download availability is not treated as redistribution permission.
8. AI-generated and teacher-authored content must remain separately labeled and must never be marked official.
9. A changed source file or edition creates a new immutable ingestion revision; it must not silently overwrite accepted evidence.
10. Official coverage remains pending until the required board, medium, standard, subject, chapter, and topic matrix is validated.

## Current limitation

The registry establishes provenance and reuse controls only. It does not import official textbook text and does not claim complete GSEB or CBSE Classes 1-10 coverage.
