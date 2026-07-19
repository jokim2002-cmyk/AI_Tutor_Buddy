from __future__ import annotations

import io
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

try:
    from dotenv import load_dotenv
except ImportError:  # packaging/runtime fallback
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from phase11_core import (
    AttachmentRecord,
    StudentLearningContext,
    attachment_prompt,
    build_tutor_system_instruction,
    clean_student_text,
    offline_tutor_response,
)


try:
    import speech_recognition as sr
except ImportError:  # optional online transcription fallback
    sr = None

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - exercised by packaged/runtime smoke tests
    genai = None
    types = None


class AIServiceError(RuntimeError):
    pass


def pcm_to_wav_bytes(
    pcm_data: bytes,
    *,
    channels: int = 1,
    sample_rate: int = 24_000,
    sample_width: int = 2,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()



VOICE_LANGUAGE_CODES = {
    "gujarati": "gu-IN",
    "hindi": "hi-IN",
    "english": "en-IN",
}

def _voice_language_code(language_hint: str) -> str:
    return VOICE_LANGUAGE_CODES.get((language_hint or "").strip().lower(), "en-IN")

@dataclass
class GyanVerseAIService:
    api_key: str | None = None
    model_name: str = "gemini-3.5-flash"
    tts_model_name: str = "gemini-3.1-flash-tts-preview"
    tts_voice_name: str = "Aoede"
    max_history_turns: int = 6
    request_timeout_ms: int = 6_000
    _client: Any = field(default=None, init=False, repr=False)
    _history: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    _online_disabled: bool = field(default=False, init=False, repr=False)
    last_backend: str = field(default="offline", init=False)
    last_error: str = field(default="", init=False)

    def __post_init__(self) -> None:
        raw_api_key = os.getenv("GEMINI_API_KEY", "") if self.api_key is None else self.api_key
        self.api_key = raw_api_key.strip()
        self.model_name = (
            self.model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        ).strip()
        self.tts_model_name = (
            self.tts_model_name
            or os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
        ).strip()
        self.tts_voice_name = (
            self.tts_voice_name or os.getenv("GEMINI_TTS_VOICE", "Aoede")
        ).strip()
        try:
            configured_timeout = int(os.getenv("GYANVERSE_AI_TIMEOUT_MS", str(self.request_timeout_ms)))
        except ValueError:
            configured_timeout = self.request_timeout_ms
        self.request_timeout_ms = max(3_000, min(configured_timeout, 20_000))
        if self.api_key and genai is not None:
            try:
                http_options = (
                    types.HttpOptions(timeout=self.request_timeout_ms)
                    if types is not None and hasattr(types, "HttpOptions")
                    else None
                )
                self._client = genai.Client(api_key=self.api_key, http_options=http_options)
            except Exception as exc:
                try:
                    # Older SDK compatibility; UI still enforces a hard response deadline.
                    self._client = genai.Client(api_key=self.api_key)
                except Exception as fallback_exc:
                    self._client = None
                    self.last_error = (
                        f"AI client setup failed: {type(exc).__name__}; "
                        f"fallback: {type(fallback_exc).__name__}"
                    )

    @property
    def configured(self) -> bool:
        return self._client is not None and types is not None and not self._online_disabled

    @property
    def transcription_available(self) -> bool:
        return self.configured or sr is not None

    @property
    def transcription_backend(self) -> str:
        if self.configured:
            return "Gemini multilingual voice"
        if sr is not None:
            return "Google web-speech fallback"
        return "Unavailable — typing fallback"

    def reset_session(self) -> None:
        self._history.clear()
        self._online_disabled = False
        self.last_backend = "offline"
        self.last_error = ""

    def disable_online_for_session(self, reason: str) -> None:
        self._online_disabled = True
        self.last_error = clean_student_text(reason, max_length=500)
        self.last_backend = "offline-fallback"

    def offline_answer(
        self,
        *,
        message: str,
        context: StudentLearningContext,
        attachments: Sequence[AttachmentRecord] = (),
        reason: str = "",
    ) -> str:
        self.last_backend = "offline-fallback" if reason else "offline"
        self.last_error = clean_student_text(reason, max_length=500)
        answer = offline_tutor_response(message, context, attachments)
        if reason:
            answer += (
                "\n\nOnline tutor was slow or unavailable, so I showed a fast local reply. "
                "Your question is still safe and you can continue typing."
            )
        return answer

    def ask(
        self,
        *,
        message: str,
        context: StudentLearningContext,
        attachments: Sequence[AttachmentRecord] = (),
    ) -> str:
        message = clean_student_text(message)
        if not self.configured:
            return self.offline_answer(
                message=message,
                context=context,
                attachments=attachments,
                reason=self.last_error if self._online_disabled else "",
            )

        instruction = build_tutor_system_instruction(context)
        history_text = "\n".join(
            f"Student: {student}\nTutor: {tutor}" for student, tutor in self._history[-self.max_history_turns :]
        )
        prompt = (
            f"{instruction}\n\n"
            f"RECENT SESSION:\n{history_text or 'No earlier messages in this session.'}\n\n"
            f"CURRENT REQUEST:\n{message or 'Review the attached homework.'}\n\n"
            f"{attachment_prompt(attachments)}"
        )
        contents: list[Any] = [prompt]
        for record in attachments:
            path = Path(record.stored_path)
            if not path.exists() or path.stat().st_size > 15 * 1024 * 1024:
                continue
            if record.mime_type.startswith("image/") or record.mime_type in {
                "application/pdf",
                "text/plain",
            }:
                contents.append(
                    types.Part.from_bytes(data=path.read_bytes(), mime_type=record.mime_type)
                )

        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=contents,
            )
            answer = clean_student_text(getattr(response, "text", ""), max_length=20_000)
            if not answer:
                raise AIServiceError("AI service returned an empty answer.")
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.disable_online_for_session(reason)
            return self.offline_answer(
                message=message,
                context=context,
                attachments=attachments,
                reason=reason,
            )

        self.last_backend = "Gemini"
        self.last_error = ""
        self._history.append((message or "[homework attachment]", answer))
        self._history = self._history[-self.max_history_turns :]
        return answer

    def _transcribe_with_web_speech(self, wav_bytes: bytes, *, language_hint: str) -> str:
        if sr is None:
            raise AIServiceError("Web-speech fallback is not installed.")
        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio = recognizer.record(source)
            transcript = recognizer.recognize_google(
                audio,
                language=_voice_language_code(language_hint),
            )
            transcript = clean_student_text(str(transcript), max_length=8_000)
            if not transcript:
                raise AIServiceError("No clear speech was detected.")
            return transcript
        except AIServiceError:
            raise
        except getattr(sr, "UnknownValueError", Exception) as exc:
            raise AIServiceError("I could not understand the recording. Please speak closer to the microphone.") from exc
        except getattr(sr, "RequestError", Exception) as exc:
            raise AIServiceError("Online voice recognition is temporarily unavailable. Typing remains available.") from exc
        except Exception as exc:
            raise AIServiceError(f"Voice fallback failed: {type(exc).__name__}: {exc}") from exc

    def transcribe(self, wav_bytes: bytes, *, language_hint: str = "Gujarati") -> str:
        if not wav_bytes:
            raise AIServiceError("No voice recording was captured.")

        gemini_error: Exception | None = None
        if self.configured:
            prompt = (
                "Transcribe only the student's spoken words. Do not answer the question. "
                "The student may speak Gujarati, Hindi, English, or mix them naturally. "
                f"Likely language: {language_hint}. Return plain editable text only."
            )
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                    ],
                )
                transcript = clean_student_text(getattr(response, "text", ""), max_length=8_000)
                if transcript:
                    return transcript
                gemini_error = AIServiceError("Gemini detected no clear speech.")
            except Exception as exc:
                gemini_error = exc

        if sr is not None:
            try:
                return self._transcribe_with_web_speech(
                    wav_bytes,
                    language_hint=language_hint,
                )
            except AIServiceError as fallback_error:
                if gemini_error is not None:
                    raise AIServiceError(
                        f"Voice transcription failed in both backends. "
                        f"Gemini: {type(gemini_error).__name__}; fallback: {fallback_error}"
                    ) from fallback_error
                raise

        if gemini_error is not None:
            raise AIServiceError(
                f"Voice transcription failed: {type(gemini_error).__name__}: {gemini_error}"
            ) from gemini_error
        raise AIServiceError(
            "Voice transcription is unavailable. Add GEMINI_API_KEY or install SpeechRecognition; typing remains available."
        )

    def synthesize(self, text: str, *, language_hint: str = "Gujarati") -> bytes:
        text = clean_student_text(text, max_length=6_000)
        if not text:
            raise AIServiceError("There is no tutor answer to speak.")
        if not self.configured:
            raise AIServiceError("Spoken answers need GEMINI_API_KEY. The text answer remains available.")
        prompt = (
            "Speak exactly the transcript below without adding or translating words. "
            "Use a warm, patient Indian teacher voice at a calm learning pace. "
            f"The likely language is {language_hint}.\n\nTRANSCRIPT:\n{text}"
        )
        try:
            response = self._client.models.generate_content(
                model=self.tts_model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.tts_voice_name
                            )
                        )
                    ),
                ),
            )
            pcm_data = response.candidates[0].content.parts[0].inline_data.data
            if not pcm_data:
                raise AIServiceError("TTS returned no audio.")
            return pcm_to_wav_bytes(pcm_data)
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"Spoken answer failed: {type(exc).__name__}: {exc}") from exc
