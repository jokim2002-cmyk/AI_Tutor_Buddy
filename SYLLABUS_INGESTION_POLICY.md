# GyanVerse Immutable Syllabus Ingestion Policy

## Purpose

This policy defines how validated syllabus artifacts enter the local-first GyanVerse curriculum store without silent overwrite, unverifiable mutation, or destructive rollback.

## Storage model

The ingestion store is content-addressed and append-only:

- `objects/<sha256-prefix>/<sha256>` stores immutable artifact bytes.
- `manifests/<revision-id>.json` stores immutable ingestion evidence.
- `active/<package-key>.json` is an atomic pointer to the currently active revision.
- `activation_events/<package-key>/` stores append-only activation and rollback events.
- `.staging/` holds temporary files only until checksums pass.

Runtime stores remain under ignored application data. Tests use temporary directories and do not alter the user's installed syllabus packages.

## Revision identity

A revision ID is a SHA-256 digest of canonical identity fields:

- package key,
- board, medium, standard and subject,
- academic year and edition,
- official source record ID,
- ingestion mode,
- artifact names, roles, media types, sizes and SHA-256 fingerprints.

Creation timestamps and active-pointer history do not change the immutable revision identity.

## Required gates

1. The source record must exist in the official source registry.
2. Source board and supported standard must match the package.
3. Metadata ingestion requires a source approved for metadata or content.
4. Textbook-content ingestion requires `approved_for_content` and verified reuse rights.
5. Every artifact is hashed before storage and re-hashed after copying.
6. Duplicate filenames inside one manifest are rejected.
7. An exact duplicate revision is rejected.
8. The same package edition with different bytes is rejected as an edition conflict.
9. A changed artifact must use a new edition or revision label.
10. Stored objects and manifests are verified before activation.
11. Active pointers are replaced atomically.
12. Mutation operations use a cross-process lock.
13. Rollback verifies the target revision and package identity before activation.
14. Rollback never deletes the newer revision or stored objects.
15. Tampered or missing objects block activation and rollback.

## Recovery behavior

A failed ingestion must not change the active pointer. Successfully stored content-addressed objects may remain as harmless unreferenced objects, but no manifest is activated until all validation passes. A later maintenance command may report and clean verified unreferenced objects; automatic deletion is intentionally excluded from this foundation.

A stale lock is not removed automatically because doing so could allow two writers to mutate the store. Stale-lock recovery must be an explicit future administrative action with process verification.

## Current limitation

This foundation does not download textbooks, approve reuse rights, import production curriculum content, or connect the ingestion store to the app UI. The current official source inventory contains no content-approved source, so textbook-content ingestion remains blocked by design.
