# Phase 11 Implementation Checkpoint

Base checkpoint: `master / 3b2d16b`

## Implemented in this cohesive source batch

- Responsive full-width Flet shell with a hidden `NavigationDrawer`.
- Student-friendly top bar and original GyanVerse brand assets.
- Tutor conversation bubbles and a fixed multiline bottom composer.
- Explain, Homework Help, Revision and Exam Answer modes.
- First-use onboarding for board (GSEB, CBSE), medium, standard (1–10) and preferred language.
- Atomic local persistence of current student, subject, chapter and topic context.
- Conservative context extraction from typed/spoken messages.
- Multi-file homework attachment picker for images, PDF and common documents.
- Local attachment hashing, size/type limits, preview, cancellation, removal and history deletion.
- Hint-first AI request contract with deterministic offline fallback.
- Optional Gemini image/PDF understanding through inline file bytes.
- Optional Android/Windows microphone recording with permission request and editable transcript.
- Optional spoken tutor output with readable-text fallback.
- Board-neutral syllabus schema, source validation, importer, repository lookup and coverage reporting for GSEB and CBSE packages.
- Explicit separation of official, teacher-authored, AI-generated and metadata-only content.
- Cross-platform Flet packaging configuration with Android minimum SDK 24.
- Android and Windows build scripts with UTF-8 safeguards and dynamic project-root resolution.
- Comprehensive automated regression tests verified dynamically via `validate_phase11.ps1`.

## Intentionally not claimed as passed yet

The following remain pending and are clearly separated from implemented source and automated test passes:

1. Flet runtime visual acceptance at common phone widths.
2. Drawer and Android back-button behaviour on a physical phone.
3. Microphone permission, Gujarati/Hindi/English transcription and editable recognised text.
4. Spoken-answer playback and graceful fallback.
5. Camera/provider/gallery/PDF/document selection on the installed APK.
6. Homework image/PDF understanding with the configured Gemini key.
7. Windows EXE build and workflow acceptance.
8. Android APK build, installation and workflow acceptance.
9. Official GSEB and CBSE source-package acquisition, provenance validation and real coverage reporting.
10. Final roadmap update, release commit and push.

## Safety decisions

- Existing TutorEngine/database behaviour is preserved.
- `legacy_voice_tutor.py` remains available, but its binary desktop audio dependencies are excluded from Android production dependencies.
- No official GSEB textbook content is invented or bundled.
- Local databases, student files, `.env`, keys and generated builds stay untracked.

## Desktop voice and no-console acceptance hotfix

- Desktop microphone capture now records a real mono WAV file instead of relying only on raw stream events.
- Voice transcription uses Gemini when configured and a Gujarati/Hindi/English web-speech fallback when needed.
- A `pythonw.exe` desktop launcher and shortcut path keep the app console-free while preserving file logs.
- Final Android microphone and spoken-output acceptance remain release gates.
