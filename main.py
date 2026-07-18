from __future__ import annotations

import logging
import wave
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

import flet as ft
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
from dotenv import load_dotenv
from google import genai
from google.genai import types

APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "ai_tutor.log"

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

_tts_lock = threading.RLock()


def write_pcm_wave(
    path: str,
    pcm_data: bytes,
    *,
    channels: int = 1,
    sample_rate: int = 24_000,
    sample_width: int = 2,
) -> None:
    """Write Gemini TTS raw PCM bytes to a standard WAV file."""
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)


def clean_response_text(text: str) -> str:
    """Remove markdown characters that should not be spoken aloud."""
    cleaned = re.sub(r"[*_`#>]", "", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def main(page: ft.Page) -> None:
    page.title = "AI Tutor Buddy"
    page.window.width = 400
    page.window.height = 700
    page.padding = 16

    chat_history = ft.ListView(expand=True, spacing=10, auto_scroll=True)
    user_input = ft.TextField(
        hint_text="Ask your doubt...",
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
        """Generate and play a warm female tutor voice using Gemini TTS."""
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


    def send_message(_event: object = None) -> None:
        nonlocal chat_session
        user_text = (user_input.value or "").strip()
        if not user_text:
            return

        if AI_CLIENT is None:
            add_message("Error: GEMINI_API_KEY was not found in the .env file.", color="red")
            return

        LOGGER.info("Sending message to Gemini")
        set_busy(True, "Tutor is thinking...")
        add_message(f"Student: {user_text}", color="blue", bold=True)
        user_input.value = ""
        page.update()

        try:
            system_instruction = (
                "You are a strict but friendly AI Tutor. "
                "Never blindly agree with the student. Verify the student's logic first. "
                "Guide with hints and reasoning instead of immediately giving the final answer. "
                "Use simple language suitable for the student's class level. "
                "Reply only in Indian English, Hindi, or Gujarati. Match the student's language. "
                "If the student mixes these languages, reply naturally in the same mix. "
                "Do not use markdown or asterisks."
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

            LOGGER.info("Gemini response received successfully")
            add_message(f"Tutor: {clean_text}", color="green")
            status_text.value = "Speaking..."
            page.update()
            speak(clean_text)
        except Exception as exc:
            LOGGER.exception("Gemini request failed")
            add_message(f"Tutor error: {type(exc).__name__}: {exc}", color="red")
        finally:
            set_busy(False, "Ready")

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

            # SpeechRecognition launches a FLAC converter subprocess. On some
            # Windows + Python 3.14 + Flet desktop sessions, inheriting stderr
            # raises WinError 50. Force a valid pipe only for this conversion.
            original_popen = subprocess.Popen

            def safe_popen(*args, **kwargs):
                kwargs.setdefault("stderr", subprocess.PIPE)
                return original_popen(*args, **kwargs)

            subprocess.Popen = safe_popen
            try:
                transcript = recognizer.recognize_google(
                    audio, language="en-IN"
                ).strip()
            finally:
                subprocess.Popen = original_popen
            if not transcript:
                raise sr.UnknownValueError("No speech was detected.")

            LOGGER.info("Speech recognized successfully")
            user_input.value = transcript
            user_input.hint_text = "Ask your doubt..."
            page.update()
        except sr.UnknownValueError:
            LOGGER.warning("Speech was not understood")
            add_message("Voice error: Speech samajh nahi aayi. Mic ke paas clearly bolkar retry karo.", color="red")
        except sr.RequestError as exc:
            LOGGER.exception("Google Speech Recognition request failed")
            add_message(f"Voice service error: Internet/STT service unavailable: {exc}", color="red")
        except sd.PortAudioError as exc:
            LOGGER.exception("Microphone/PortAudio error")
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

    LOGGER.info("AI Tutor Buddy started | model=%s | tts_model=%s | voice=%s | log=%s", MODEL_NAME, TTS_MODEL_NAME, TTS_VOICE_NAME, LOG_FILE)


if __name__ == "__main__":
    ft.run(main)
