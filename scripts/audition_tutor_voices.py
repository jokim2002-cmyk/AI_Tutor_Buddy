#!/usr/bin/env python3
"""
Audition utility for GyanVerse Academy natural Indian female teacher voices.
Generates multilingual audio samples (English, Hindi, Gujarati) for Kore, Aoede, and Leda.
Saves WAV files in .local_voice_auditions/ for manual listening and evaluation.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from phase11_core import StudentLearningContext
from phase11_ai import GyanVerseAIService, AIServiceError

AUDITION_SAMPLE_TEXT = (
    "Welcome to GyanVerse Academy! "
    "आज हम गणित और विज्ञान के प्रश्न हल करेंगे। "
    "GyanVerse Academy માં તમારું સ્વાગત છે, આજે આપણે ખુબ જ સરસ અભ્યાસ કરીશું."
)

DEFAULT_VOICES = ["Kore", "Aoede", "Leda"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audition natural Indian female teacher voices for GyanVerse Academy"
    )
    parser.add_argument(
        "--voices",
        type=str,
        default=",".join(DEFAULT_VOICES),
        help="Comma-separated list of Gemini TTS voice names (default: Kore,Aoede,Leda)",
    )
    parser.add_argument(
        "--selected-voice",
        type=str,
        default="",
        help="Specific voice to audition or play",
    )
    parser.add_argument(
        "--play",
        action="store_true",
        help="Play the selected voice audio file after generation",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "natural", "local"],
        help="TTS mode for auditioning (default: auto)",
    )
    args = parser.parse_args()

    voice_list = [v.strip() for v in args.voices.split(",") if v.strip()]
    if args.selected_voice:
        if args.selected_voice not in voice_list:
            voice_list = [args.selected_voice] + voice_list
        else:
            voice_list = [args.selected_voice]

    audition_dir = PROJECT_ROOT / ".local_voice_auditions"
    audition_dir.mkdir(parents=True, exist_ok=True)

    print("=== GyanVerse Natural Teacher Voice Audition Utility ===")
    print(f"Audition Directory: {audition_dir}")
    print(f"Voices to Audition: {', '.join(voice_list)}")
    print(f"Multilingual Transcript:\n  {AUDITION_SAMPLE_TEXT}\n")

    service = GyanVerseAIService(tts_mode=args.mode)
    if not service.tts_configured and args.mode != "local":
        print("WARNING: Gemini API key is not configured or TTS client is offline.")
        print("To generate online natural neural voice samples, set GEMINI_API_KEY environment variable.")
        if not service.local_tts_available:
            print("ERROR: Neither Gemini TTS nor local Windows speech is available.")
            return 1
        print("Falling back to local SAPI voice audition.\n")

    context = StudentLearningContext(
        name="AuditionStudent", standard=7, board="GSEB", preferred_language="English"
    )

    generated_files: list[tuple[str, Path, int, str]] = []

    for voice_name in voice_list:
        output_path = audition_dir / f"tutor_audition_{voice_name}.wav"
        print(f"Generating voice audition sample for '{voice_name}'...")
        t_start = time.perf_counter()
        try:
            audio_bytes = service.synthesize(
                AUDITION_SAMPLE_TEXT,
                language_hint="Hinglish",
                voice_name=voice_name,
            )
            t_end = time.perf_counter()
            elapsed_sec = t_end - t_start
            output_path.write_bytes(audio_bytes)
            file_size = len(audio_bytes)
            backend_used = service.last_tts_backend or service.tts_backend_label
            print(
                f"  -> Saved {output_path.name} ({file_size / 1024:.1f} KB) "
                f"in {elapsed_sec:.2f}s using [{backend_used}]"
            )
            generated_files.append((voice_name, output_path, file_size, backend_used))
        except Exception as exc:
            print(f"  -> ERROR generating voice '{voice_name}': {exc}")

    print("\n--- Audition Results Summary ---")
    if not generated_files:
        print("FAIL: No voice samples were successfully generated.")
        return 1

    for voice_name, path, size, backend in generated_files:
        valid_str = "VALID WAV" if service._is_valid_wav(path.read_bytes()) else "INVALID"
        print(f"  * Voice: {voice_name:8s} | File: {path.name:25s} | Size: {size/1024:6.1f} KB | {valid_str} | Backend: {backend}")

    selected = args.selected_voice or generated_files[0][0]
    target_tuple = next((item for item in generated_files if item[0].lower() == selected.lower()), generated_files[0])
    selected_voice_name, selected_path, _, _ = target_tuple

    print(f"\nDefault/Selected Voice for Session: {selected_voice_name}")

    if args.play:
        if not service.native_playback_available:
            print("WARNING: Native desktop audio playback is unavailable on this OS platform.")
        else:
            print(f"Playing audition sample for '{selected_voice_name}' ({selected_path.name})...")
            try:
                service.play_wav_bytes(selected_path.read_bytes(), audio_path=selected_path)
                print("Playback started. Listen to evaluate voice quality.")
                time.sleep(1.0)
            except Exception as exc:
                print(f"ERROR playing audio: {exc}")

    print("\n=== Voice Audition Utility Finished Successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
