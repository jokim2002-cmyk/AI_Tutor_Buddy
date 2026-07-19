# Phase 9 — GyanVerse UI/UX

The public application is implemented with Flet and exposes student, parent, teacher, and principal experiences from one responsive desktop shell.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

Core reports, daily sync, homework generation, revision, and progress operate with the local SQLite tutor engine. Live Gemini and voice features continue to require `.env` credentials and supported audio hardware.
