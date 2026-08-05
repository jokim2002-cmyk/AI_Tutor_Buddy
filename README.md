# GyanVerse Academy / AI Tutor Buddy

GyanVerse Academy is a personal tutor application for Windows and Android targeting school students in Classes 1 through 10 across GSEB and CBSE boards. It combines the learning-intelligence engine with a mobile-first Flet interface, persistent student/class context, homework support, multilingual voice paths and a board-neutral syllabus repository foundation.

## Current development checkpoint

Phase 11 source implementation is in progress. Automated regression tests and configuration validation pass cleanly (`validate_phase11.ps1`).

This is **not yet the final release**. Windows packaging, Android packaging, official curriculum package acquisition, and real-device acceptance—especially microphone, spoken answers, photo/file attachment and narrow-phone layout—must pass before the final release candidate is approved.

## Student workflow

1. On first launch, set board (GSEB or CBSE), medium, standard (1–10) and tutor language.
2. Save the subject, chapter and topic currently being taught at school.
3. Open **Tutor** and choose Explain, Homework Help, Revision or Exam Answer mode.
4. Type a question, use the microphone, or attach homework with the `+` button.
5. Review progress, revision priorities, homework history and syllabus coverage from the hidden menu.

## Run locally

```powershell
cd D:\Ai_Tutor_Buddy
python -m pip install -r requirements.txt
flet run main.py
```

The same commands work from any clone location.

## Configuration

Create a local `.env` file when Gemini services are required:

```text
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TTS_MODEL=gemini-3.1-flash-tts-preview
GEMINI_TTS_VOICE=Aoede
```

Never commit `.env`, API keys, signing keys or student databases.

Without an API key, core navigation, student context, local history and deterministic tutor guidance remain available. Online image/PDF understanding, speech-to-text and generated spoken answers show a clear fallback.

## Validation and builds

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_phase11.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_android_apk.ps1
```

Android minimum SDK remains 24 in `pyproject.toml`. Runtime packaging excludes the legacy desktop audio stack so Android does not depend on `sounddevice` or `soundfile`.

## Syllabus content integrity

The importer accepts structured JSON packages for supported boards (GSEB and CBSE) with board, medium, standard, subject, textbook, source, edition, chapter, topic and `content_origin` metadata. Official material, teacher-authored material, AI-generated practice and metadata-only coverage are kept separate. The schema example contains no official textbook content.

## Repository workflow

- Work phase-wise in cohesive batches.
- Audit and back up before edits.
- Keep tests and release gates green.
- Do not commit generated builds, databases, `.env` or signing material.
- Commit and push only after the intended validation checkpoint passes.
