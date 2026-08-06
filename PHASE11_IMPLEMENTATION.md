# Phase 11 Implementation & Phase 1 Checkpoint

Base checkpoint: `master / 7c04f78`

## Implemented and Verified Functionality

- **Instant Conversational Routing**: Implemented and manually verified in Windows UI. Instant greetings (`hello`, `namaste`) bypass online AI with ~0.0ms latency.
- **Academic Text Streaming**: Implemented and manually verified in Windows UI. Academic text streaming renders initial visible response in ~3.4s and completes in ~3.4s.
- **Natural Voice Selection**: `Aoede` is the selected natural Indian female teacher voice.
- **1-Request Streaming Audio Pipeline**: Natural TTS uses exactly one streaming provider request (`generate_content_stream`) per tutor answer. Play, prefetch, and Replay share the single request/cache identity.
- **Default TTS Mode**: Default TTS mode is `natural`.
- **Prohibited Windows Local Fallback**: Windows robotic SAPI voice fallback is strictly prohibited in `natural` mode to ensure consistent natural voice UX.
- **Visible Error States**: Quota (`429`) and timeout errors update UI status controls to explicit persistent states (`Natural voice temporarily unavailable • quota limit`, `Natural voice failed • Retry`).
- **Diagnostic Utilities**: [`scripts/diagnose_tutor_voice.py`](file:///D:/Ai_Tutor_Buddy/scripts/diagnose_tutor_voice.py) with `--stream` support and [`scripts/benchmark_tutor_latency.py`](file:///D:/Ai_Tutor_Buddy/scripts/benchmark_tutor_latency.py).

## Intentionally Not Claimed as Passed Yet

1. **Real Aoede Streaming Playback Acceptance**: Remaining pending because the natural TTS provider returned `429 RESOURCE_EXHAUSTED`. (The 429 status is logged as provider rate limit without asserting an unverified daily quota category).
2. **Google Login & Cloud Sync**: Pending future phase.
3. **Curriculum & Syllabus Ingestion**: Pending official textbook dataset acquisition.
4. **Premium UI Redesign**: Pending future phase.
5. **Windows Packaged EXE (.exe)**: Build and workflow acceptance pending.
6. **Android Packaged APK (.apk)**: Build, physical device installation, and workflow acceptance pending.

## Safety Decisions

- Existing TutorEngine and local database behavior preserved.
- No official GSEB/CBSE textbook content is invented or bundled.
- Local databases, student files, `.env`, keys, logs, and generated cache files remain untracked.

## Phase 2A — Conversation Persistence and Cloud-Sync Foundation

Implemented in source, pending live cloud acceptance:

- Local SQLite conversations and messages survive app restarts.
- A stable local device owner keeps offline data isolated before sign-in.
- Recent stored student/tutor turns restore the bounded tutor session context.
- Every local write creates a durable outbox event for later cloud upload.
- Firebase Authentication and Firestore REST adapters are present with no embedded secrets.
- Firestore rules template isolates every user's data under their Firebase UID.

Still pending:

- Visible Google sign-in/sign-out UI and encrypted token persistence.
- Firebase project configuration and deployed security rules.
- Real upload, pull, conflict resolution, delete propagation and two-device acceptance.
- Attachment/audio cloud storage. The first sync scope is chat text and metadata only.
