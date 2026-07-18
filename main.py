from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

import flet as ft
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
from dotenv import load_dotenv
from google import genai
from google.genai import types

from tutor_engine import TutorEngine, TutorEngineError

APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "ai_tutor.log"
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
LOGGER = logging.getLogger("ai_tutor")

load_dotenv(APP_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
TTS_MODEL_NAME = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview").strip()
TTS_VOICE_NAME = os.getenv("GEMINI_TTS_VOICE", "Aoede").strip()
AI_CLIENT = genai.Client(api_key=API_KEY) if API_KEY else None

RECORD_SECONDS = 5
SAMPLE_RATE = 44_100
DEFAULT_STUDENT_ID = os.getenv("AI_TUTOR_STUDENT_ID", "student-1").strip() or "student-1"

_tts_lock = threading.RLock()


def write_pcm_wave(
    path: str,
    pcm_data: bytes,
    *,
    channels: int = 1,
    sample_rate: int = 24_000,
    sample_width: int = 2,
) -> None:
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)


def clean_response_text(text: str) -> str:
    cleaned = re.sub(r"[*_`#>]", "", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def main(page: ft.Page) -> None:
    page.title = "AI Tutor Buddy"
    page.window.width = 400
    page.window.height = 700
    page.padding = 16

    tutor_engine = TutorEngine(
        db_path=DATA_DIR / "ai_tutor.db",
        ai_client=AI_CLIENT,
        model_name=MODEL_NAME,
    )
    tutor_engine.ensure_student(
        student_id=DEFAULT_STUDENT_ID,
        name="Student",
        grade=7,
        board="CBSE",
        preferred_language="English (India)",
    )

    chat_history = ft.ListView(expand=True, spacing=10, auto_scroll=True)
    user_input = ft.TextField(
        hint_text="Ask your doubt or type /help...",
        expand=True,
        on_submit=lambda event: send_message(event),
    )
    status_text = ft.Text("Ready", size=12)
    chat_session = None

    def add_message(message: str, *, color: str = "black", bold: bool = False) -> None:
        chat_history.controls.append(
            ft.Text(
                message,
                color=color,
                weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
                selectable=True,
            )
        )
        page.update()

    def set_busy(is_busy: bool, status: str) -> None:
        mic_button.disabled = is_busy
        send_button.disabled = is_busy
        user_input.disabled = is_busy
        status_text.value = status
        page.update()

    def speak(text: str) -> None:
        temp_audio_path: Optional[str] = None
        try:
            if AI_CLIENT is None:
                raise RuntimeError("GEMINI_API_KEY was not found.")

            tts_prompt = (
                "Speak exactly the transcript below without translating or adding words. "
                "Use a warm, clear, patient female Indian teacher voice. "
                "Use a natural Indian English accent for English text, standard Hindi "
                "pronunciation for Hindi text, and natural Gujarati pronunciation for "
                "Gujarati text. The supported languages are only Indian English, Hindi, "
                "and Gujarati. Keep a calm teaching pace and friendly confidence.\n\n"
                f"TRANSCRIPT:\n{text}"
            )

            with _tts_lock:
                LOGGER.info(
                    "Generating Gemini TTS | model=%s | voice=%s",
                    TTS_MODEL_NAME,
                    TTS_VOICE_NAME,
                )
                response = AI_CLIENT.models.generate_content(
                    model=TTS_MODEL_NAME,
                    contents=tts_prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=TTS_VOICE_NAME,
                                )
                            )
                        ),
                    ),
                )
                try:
                    audio_data = response.candidates[0].content.parts[0].inline_data.data
                except (AttributeError, IndexError, TypeError) as exc:
                    raise RuntimeError("Gemini TTS returned no playable audio.") from exc
                if not audio_data:
                    raise RuntimeError("Gemini TTS returned empty audio data.")

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_audio_path = temp_file.name

                write_pcm_wave(temp_audio_path, audio_data)
                samples, sample_rate = sf.read(temp_audio_path, dtype="float32")
                sd.play(samples, sample_rate)
                sd.wait()
            LOGGER.info("Gemini female TTS completed")
        except Exception as exc:
            LOGGER.exception("Gemini female TTS failed")
            add_message(f"TTS error: {type(exc).__name__}: {exc}", color="red")
        finally:
            if temp_audio_path:
                try:
                    Path(temp_audio_path).unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not delete temporary TTS file: %s", temp_audio_path)

    def command_help() -> str:
        return (
            "Core Tutor commands:\n"
            "/sync Subject | Chapter | What school taught today\n"
            "/homework Subject | Chapter | Number of questions\n"
            "/check HomeworkID | Answer 1 || Answer 2 || Answer 3\n"
            "/progress\n"
            "/today\n"
            "/help\n\n"
            "Example: /sync Mathematics | Fractions | Addition of unlike fractions"
        )

    def handle_core_command(text: str) -> Optional[str]:
        lowered = text.lower().strip()

        if lowered == "/help":
            return command_help()

        if lowered == "/progress":
            return tutor_engine.format_progress(DEFAULT_STUDENT_ID)

        if lowered == "/today":
            return tutor_engine.format_today_summary(DEFAULT_STUDENT_ID)

        if lowered.startswith("/sync "):
            parts = [part.strip() for part in text[6:].split("|", 2)]
            if len(parts) != 3 or not all(parts):
                return "Use: /sync Subject | Chapter | What school taught today"
            sync = tutor_engine.record_daily_sync(
                student_id=DEFAULT_STUDENT_ID,
                subject=parts[0],
                chapter=parts[1],
                topic=parts[2],
            )
            return (
                f"Daily study saved. Subject: {sync['subject']}, "
                f"Chapter: {sync['chapter']}, Topic: {sync['topic']}."
            )

        if lowered.startswith("/homework "):
            parts = [part.strip() for part in text[10:].split("|", 2)]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                return "Use: /homework Subject | Chapter | Number of questions"
            count = 5
            if len(parts) == 3 and parts[2]:
                try:
                    count = int(parts[2])
                except ValueError:
                    return "Question count must be a number from 1 to 10."
            homework = tutor_engine.generate_homework(
                student_id=DEFAULT_STUDENT_ID,
                subject=parts[0],
                chapter=parts[1],
                question_count=count,
            )
            lines = [f"Homework ID: {homework['homework_id']}"]
            for item in homework["questions"]:
                lines.append(f"{item['number']}. {item['question']}")
            lines.append(
                "Submit using: /check HomeworkID | Answer 1 || Answer 2 || Answer 3"
            )
            return "\n".join(lines)

        if lowered.startswith("/check "):
            body = text[7:].strip()
            if "|" not in body:
                return "Use: /check HomeworkID | Answer 1 || Answer 2 || Answer 3"
            homework_id, answer_text = [part.strip() for part in body.split("|", 1)]
            answers = [item.strip() for item in answer_text.split("||")]
            result = tutor_engine.check_homework(
                student_id=DEFAULT_STUDENT_ID,
                homework_id=homework_id,
                answers=answers,
            )
            lines = [
                f"Homework checked: {result['score']}/{result['total']}",
                f"Mastery: {result['mastery_percent']}%",
            ]
            for feedback in result["feedback"]:
                lines.append(
                    f"{feedback['number']}. {feedback['status']}: {feedback['feedback']}"
                )
            return "\n".join(lines)

        return None

    def send_message(_event: object = None) -> None:
        nonlocal chat_session
        user_text = (user_input.value or "").strip()
        if not user_text:
            return

        LOGGER.info("Processing student message")
        set_busy(True, "Tutor is thinking...")
        add_message(f"Student: {user_text}", color="blue", bold=True)
        user_input.value = ""
        page.update()

        try:
            command_response = handle_core_command(user_text)
            if command_response is not None:
                clean_text = clean_response_text(command_response)
            else:
                if AI_CLIENT is None:
                    raise RuntimeError("GEMINI_API_KEY was not found in the .env file.")

                memory_context = tutor_engine.build_student_context(DEFAULT_STUDENT_ID)
                system_instruction = (
                    "You are a strict but friendly AI Tutor. "
                    "Never blindly agree with the student. Verify the student's logic first. "
                    "Use a hint-first method: first ask or give a small clue, then guide steps, "
                    "and reveal the final answer only when necessary. "
                    "Use simple language suitable for the student's class level. "
                    "Identify likely misconception or careless error when relevant. "
                    "Reply only in Indian English, Hindi, or Gujarati and match the student's language. "
                    "Do not use markdown or asterisks.\n\n"
                    f"STUDENT MEMORY:\n{memory_context}"
                )
                if chat_session is None:
                    chat_session = AI_CLIENT.chats.create(
                        model=MODEL_NAME,
                        config={"system_instruction": system_instruction},
                    )
                response = chat_session.send_message(user_text)
                clean_text = clean_response_text(response.text)
                if not clean_text:
                    raise RuntimeError("Gemini returned an empty response.")
                tutor_engine.record_learning_interaction(
                    student_id=DEFAULT_STUDENT_ID,
                    user_text=user_text,
                    tutor_text=clean_text,
                )

            add_message(f"Tutor: {clean_text}", color="green")
            status_text.value = "Speaking..."
            page.update()
            speak(clean_text)
        except TutorEngineError as exc:
            LOGGER.exception("Tutor engine request failed")
            add_message(f"Tutor engine error: {exc}", color="red")
        except Exception as exc:
            LOGGER.exception("Tutor request failed")
            add_message(f"Tutor error: {type(exc).__name__}: {exc}", color="red")
        finally:
            set_busy(False, "Ready")
            user_input.focus()

    def listen_audio(_event: object = None) -> None:
        set_busy(True, f"Listening for {RECORD_SECONDS} seconds...")
        temp_path: Optional[str] = None
        try:
            device = sd.query_devices(kind="input")
            LOGGER.info("Using microphone: %s", device.get("name", "Unknown"))
            recording = sd.rec(
                int(RECORD_SECONDS * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = temp_file.name
            sf.write(temp_path, recording, SAMPLE_RATE)

            status_text.value = "Converting speech to text..."
            page.update()

            recognizer = sr.Recognizer()
            with sr.AudioFile(temp_path) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.record(source)

            original_popen = subprocess.Popen

            def safe_popen(*args, **kwargs):
                kwargs.setdefault("stderr", subprocess.PIPE)
                return original_popen(*args, **kwargs)

            subprocess.Popen = safe_popen
            try:
                transcript = recognizer.recognize_google(audio, language="en-IN").strip()
            finally:
                subprocess.Popen = original_popen

            if not transcript:
                raise sr.UnknownValueError("No speech was detected.")

            LOGGER.info("Speech recognized successfully")
            user_input.value = transcript
            user_input.hint_text = "Ask your doubt or type /help..."
            page.update()
        except sr.UnknownValueError:
            add_message(
                "Voice error: Speech samajh nahi aayi. Mic ke paas clearly bolkar retry karo.",
                color="red",
            )
        except sr.RequestError as exc:
            add_message(f"Voice service error: Internet/STT unavailable: {exc}", color="red")
        except sd.PortAudioError as exc:
            add_message(f"Microphone error: {exc}", color="red")
        except Exception as exc:
            LOGGER.exception("Unexpected voice error")
            add_message(f"Voice error: {type(exc).__name__}: {exc}", color="red")
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not delete temporary audio file: %s", temp_path)
            set_busy(False, "Ready")

    send_button = ft.ElevatedButton("Send", on_click=send_message)
    mic_button = ft.IconButton(
        icon=ft.Icons.MIC,
        icon_color="blue",
        tooltip="Record voice for 5 seconds",
        on_click=listen_audio,
    )

    page.add(
        ft.Text("AI Tutor Buddy", size=24, weight=ft.FontWeight.BOLD, color="blue"),
        status_text,
        chat_history,
        ft.Row([user_input, mic_button, send_button]),
    )

    add_message("Tutor: Phase 5 Core Engine ready. Type /help to see study commands.", color="green")
    LOGGER.info(
        "AI Tutor Buddy started | model=%s | tts_model=%s | voice=%s | database=%s",
        MODEL_NAME,
        TTS_MODEL_NAME,
        TTS_VOICE_NAME,
        tutor_engine.db_path,
    )


if __name__ == "__main__":
    ft.run(main)
