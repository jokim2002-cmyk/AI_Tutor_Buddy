# GyanVerse Official Source Metadata Snapshot Policy

## Purpose

This policy defines how GyanVerse records verifiable evidence about an official GSEB, GSSTB, CBSE, or NCERT source without copying textbook pages or treating web availability as content-reuse permission.

## Snapshot evidence

A metadata snapshot may contain only:

- registered official source ID and authority,
- requested and final HTTPS URLs,
- same-host redirect chain,
- HTTP method and status,
- a limited allowlist of non-sensitive response headers,
- acquisition timestamp in UTC,
- source governance statuses,
- a deterministic SHA-256 snapshot ID.

Response bodies, textbook text, cookies, authorization values, and arbitrary server headers are excluded.

## Network behavior

1. Dry-run preview performs no network request.
2. The preferred probe method is `HEAD`.
3. When a server explicitly rejects `HEAD` with HTTP 405 or 501, the transport may open a `GET` request with `Range: bytes=0-0`.
4. The fallback request must not read or store response-body bytes.
5. Every requested URL, redirect, and final URL must remain HTTPS and on the exact registered official host.
6. Embedded URL credentials, non-default HTTPS ports, fragments, and cross-host redirects are rejected.
7. HTTP failures and unavailable servers do not create ingestion evidence.

## Header allowlist

Only these normalized response headers may be recorded:

- accept-ranges,
- cache-control,
- content-language,
- content-length,
- content-type,
- date,
- etag,
- expires,
- last-modified,
- location.

Headers such as `set-cookie`, authorization data, internal tracing values, and unknown headers are discarded.

## Integrity and ingestion

1. Snapshot evidence is serialized as canonical JSON.
2. `snapshot_id` is the SHA-256 digest of the canonical evidence payload.
3. Written JSON is immediately read back and revalidated.
4. The ingestion bridge always uses `ingestion_mode="metadata"`.
5. Snapshot artifacts use role `official_source_snapshot`.
6. The immutable ingestion engine supplies object checksum verification, edition-conflict rejection, atomic activation, activation history, and non-destructive rollback.
7. A changed snapshot under the same package edition is rejected. The operator must assign a new edition or revision label.

## Current limitation

This foundation does not download textbook files, parse curriculum pages, approve content reuse, or connect snapshots to the application UI. Automated tests use deterministic fake transports; controlled live probes are a separate manual acceptance step.
