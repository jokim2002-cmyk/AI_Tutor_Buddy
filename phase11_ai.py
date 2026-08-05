from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    format_tutor_response,
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
    request_timeout_ms: int = 25_000
    tts_timeout_ms: int = 60_000
    tts_backend: str = "local-first"
    tts_cache_dir: Path | None = None
    _client: Any = field(default=None, init=False, repr=False)
    _tts_client: Any = field(default=None, init=False, repr=False)
    _history: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    _retry_after_monotonic: float = field(default=0.0, init=False, repr=False)
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    last_backend: str = field(default="offline", init=False)
    last_error: str = field(default="", init=False)
    last_tts_backend: str = field(default="", init=False)

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
        self.request_timeout_ms = max(25_000, min(configured_timeout, 35_000))

        try:
            configured_tts_timeout = int(
                os.getenv("GYANVERSE_TTS_TIMEOUT_MS", str(self.tts_timeout_ms))
            )
        except ValueError:
            configured_tts_timeout = self.tts_timeout_ms
        self.tts_timeout_ms = max(45_000, min(configured_tts_timeout, 90_000))
        self.tts_backend = (
            os.getenv("GYANVERSE_TTS_BACKEND", self.tts_backend).strip().lower()
            or "local-first"
        )
        if self.tts_backend not in {"local-first", "gemini-first", "local-only", "gemini-only"}:
            self.tts_backend = "local-first"
        if self.tts_cache_dir is None:
            self.tts_cache_dir = Path(__file__).resolve().parent / "data" / "tts_cache"
        self.tts_cache_dir = Path(self.tts_cache_dir)
        self.tts_cache_dir.mkdir(parents=True, exist_ok=True)

        if self.api_key and genai is not None:
            def create_client(timeout_ms: int) -> Any:
                http_options = (
                    types.HttpOptions(timeout=timeout_ms)
                    if types is not None and hasattr(types, "HttpOptions")
                    else None
                )
                try:
                    return genai.Client(api_key=self.api_key, http_options=http_options)
                except Exception:
                    # Older SDK compatibility. UI-level deadlines still protect the
                    # visible interaction even when the SDK has no timeout option.
                    return genai.Client(api_key=self.api_key)

            text_error: Exception | None = None
            tts_error: Exception | None = None
            try:
                self._client = create_client(self.request_timeout_ms)
            except Exception as exc:
                text_error = exc
                self._client = None
            try:
                self._tts_client = create_client(self.tts_timeout_ms)
            except Exception as exc:
                tts_error = exc
                self._tts_client = None

            if self._client is None and self._tts_client is None:
                self.last_error = (
                    f"AI client setup failed: text={type(text_error).__name__}; "
                    f"voice={type(tts_error).__name__}"
                )

    @property
    def configured(self) -> bool:
        return (
            self._client is not None
            and types is not None
            and time.monotonic() >= self._retry_after_monotonic
        )

    @property
    def tts_configured(self) -> bool:
        return self._tts_client is not None and types is not None

    @property
    def local_tts_available(self) -> bool:
        return sys.platform == "win32" and shutil.which("powershell.exe") is not None

    @property
    def native_playback_available(self) -> bool:
        return sys.platform == "win32"

    @property
    def tts_backend_label(self) -> str:
        if self.local_tts_available and self.tts_backend != "gemini-only":
            return "local desktop voice"
        if self.tts_configured:
            return "Gemini voice"
        return "voice unavailable"

    @property
    def retry_after_seconds(self) -> int:
        return max(0, int(round(self._retry_after_monotonic - time.monotonic())))

    @property
    def status_label(self) -> str:
        if self.last_backend != "offline-fallback":
            return self.last_backend
        retry_seconds = self.retry_after_seconds
        if retry_seconds > 0:
            return f"local tutor • online retry in {retry_seconds}s"
        return "local tutor • online retry ready"

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
        self._retry_after_monotonic = 0.0
        self._consecutive_failures = 0
        self.last_backend = "offline"
        self.last_error = ""

    def defer_online_after_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        retry_delay = min(30, 2 ** min(self._consecutive_failures, 5))
        self._retry_after_monotonic = time.monotonic() + retry_delay
        self.last_error = clean_student_text(reason, max_length=500)
        self.last_backend = "offline-fallback"

    def disable_online_for_session(self, reason: str) -> None:
        # Backwards-compatible alias. A failure now creates a short retry
        # cooldown instead of permanently disabling online tutoring.
        self.defer_online_after_failure(reason)

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
        raw_answer = offline_tutor_response(
            message,
            context,
            attachments,
        )
        answer = format_tutor_response(
            raw_answer,
            student_message=message,
        )
        self._history.append((message or "[homework attachment]", answer))
        self._history = self._history[-self.max_history_turns :]
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
            if self._client is None or types is None:
                reason = self.last_error or "Online AI is not configured on this device."
            else:
                reason = self.last_error or "Online AI is waiting for its retry cooldown."
            return self.offline_answer(
                message=message,
                context=context,
                attachments=attachments,
                reason=reason,
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
            raw_text = str(getattr(response, "text", "") or "")
            answer = format_tutor_response(
                raw_text,
                student_message=message,
            )
            if not answer:
                raise AIServiceError("AI service returned an empty answer.")
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.defer_online_after_failure(reason)
            return self.offline_answer(
                message=message,
                context=context,
                attachments=attachments,
                reason=reason,
            )

        self.last_backend = "Gemini"
        self.last_error = ""
        self._retry_after_monotonic = 0.0
        self._consecutive_failures = 0
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
                start = time.perf_counter()

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

    @staticmethod
    def _is_valid_wav(audio_bytes: bytes) -> bool:
        return (
            isinstance(audio_bytes, (bytes, bytearray))
            and len(audio_bytes) > 44
            and audio_bytes.startswith(b"RIFF")
            and b"WAVE" in audio_bytes[:16]
        )

    def _tts_cache_path(self, text: str, language_hint: str) -> Path:
        digest = hashlib.sha256(
            (
                "gyanverse-tts-v14\n"
                + self.tts_backend
                + "\n"
                + language_hint.strip().lower()
                + "\n"
                + text
            ).encode("utf-8")
        ).hexdigest()
        return Path(self.tts_cache_dir) / f"{digest}.wav"

    def _read_cached_tts(self, path: Path) -> bytes | None:
        try:
            audio_bytes = path.read_bytes()
        except OSError:
            return None
        if self._is_valid_wav(audio_bytes):
            self.last_tts_backend = "cached voice"
            return audio_bytes
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    @staticmethod
    def _write_tts_cache(path: Path, audio_bytes: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(audio_bytes)
        temporary.replace(path)

    def _synthesize_windows_sapi(self, text: str, *, language_hint: str) -> bytes:
        powershell = shutil.which("powershell.exe")
        if sys.platform != "win32" or powershell is None:
            raise AIServiceError("Local Windows voice is unavailable.")

        script = r'''
param(
    [Parameter(Mandatory = $true)][string]$TextPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$LanguageHint
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @(
        $synth.GetInstalledVoices() |
            Where-Object { $_.Enabled }
    )
    if ($voices.Count -eq 0) {
        throw "No enabled Windows speech voice is installed."
    }

    $language = $LanguageHint.Trim().ToLowerInvariant()
    $preferredCulture = if ($language -match "gujarati|gu-in") {
        "gu-IN"
    }
    elseif ($language -match "hindi|hi-in|hinglish") {
        "hi-IN"
    }
    else {
        "en-IN"
    }

    $preferredPrefix = $preferredCulture.Substring(0, 2)
    $voice = $voices |
        Where-Object { $_.VoiceInfo.Culture.Name -ieq $preferredCulture } |
        Select-Object -First 1
    if ($null -eq $voice) {
        $voice = $voices |
            Where-Object {
                $_.VoiceInfo.Culture.TwoLetterISOLanguageName -ieq $preferredPrefix
            } |
            Select-Object -First 1
    }
    if ($null -eq $voice) {
        $voice = $voices |
            Where-Object {
                $_.VoiceInfo.Culture.Name -ieq "en-IN" -or
                $_.VoiceInfo.Culture.Name -ieq "en-US" -or
                $_.VoiceInfo.Culture.Name -ieq "en-GB"
            } |
            Select-Object -First 1
    }
    if ($null -eq $voice) {
        $voice = $voices | Select-Object -First 1
    }

    $synth.SelectVoice($voice.VoiceInfo.Name)
    $synth.Rate = -1
    $synth.Volume = 100
    $text = [System.IO.File]::ReadAllText(
        $TextPath,
        [System.Text.UTF8Encoding]::new($false)
    )
    $synth.SetOutputToWaveFile($OutputPath)
    $synth.Speak($text)
}
finally {
    try { $synth.SetOutputToNull() } catch {}
    $synth.Dispose()
}
'''

        with tempfile.TemporaryDirectory(prefix="gyanverse_tts_") as directory:
            temp_dir = Path(directory)
            text_path = temp_dir / "transcript.txt"
            script_path = temp_dir / "speak.ps1"
            output_path = temp_dir / "speech.wav"
            text_path.write_text(text, encoding="utf-8")
            script_path.write_text(script, encoding="utf-8")

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    "-TextPath",
                    str(text_path),
                    "-OutputPath",
                    str(output_path),
                    "-LanguageHint",
                    language_hint,
                ],
                cwd=str(Path(__file__).resolve().parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
                creationflags=creation_flags,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise AIServiceError(
                    "Local Windows voice failed"
                    + (f": {detail[:500]}" if detail else ".")
                )
            try:
                audio_bytes = output_path.read_bytes()
            except OSError as exc:
                raise AIServiceError("Local Windows voice produced no WAV file.") from exc

        if not self._is_valid_wav(audio_bytes):
            raise AIServiceError("Local Windows voice produced an invalid WAV file.")
        return audio_bytes

    def _synthesize_gemini(self, text: str, *, language_hint: str) -> bytes:
        if not self.tts_configured:
            raise AIServiceError("Gemini spoken answers are not configured.")
        prompt = (
            "Speak exactly the transcript below without adding or translating words. "
            "Use a warm, patient Indian teacher voice at a calm learning pace. "
            f"The likely language is {language_hint}.\n\nTRANSCRIPT:\n{text}"
        )
        try:
            response = self._tts_client.models.generate_content(
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
                raise AIServiceError("Gemini TTS returned no audio.")
            audio_bytes = pcm_to_wav_bytes(pcm_data)
            if not self._is_valid_wav(audio_bytes):
                raise AIServiceError("Gemini TTS returned an invalid WAV file.")
            return audio_bytes
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(
                f"Gemini spoken answer failed: {type(exc).__name__}: {exc}"
            ) from exc

    def synthesize(self, text: str, *, language_hint: str = "Gujarati") -> bytes:
        text = clean_student_text(text, max_length=6_000)
        if not text:
            raise AIServiceError("There is no tutor answer to speak.")

        cache_path = self._tts_cache_path(text, language_hint)
        cached = self._read_cached_tts(cache_path)
        if cached is not None:
            return cached

        local_allowed = self.tts_backend in {
            "local-first",
            "local-only",
            "gemini-first",
        }
        gemini_allowed = self.tts_backend in {
            "local-first",
            "gemini-first",
            "gemini-only",
        }

        order = (
            ("gemini", "local")
            if self.tts_backend == "gemini-first"
            else ("local", "gemini")
        )
        errors: list[str] = []

        for backend in order:
            if backend == "local":
                if not local_allowed or not self.local_tts_available:
                    continue
                try:
                    audio_bytes = self._synthesize_windows_sapi(
                        text,
                        language_hint=language_hint,
                    )
                    self.last_tts_backend = "local desktop voice"
                    self._write_tts_cache(cache_path, audio_bytes)
                    return audio_bytes
                except Exception as exc:
                    errors.append(f"local={type(exc).__name__}: {exc}")
                    if self.tts_backend == "local-only":
                        break
            else:
                if not gemini_allowed or not self.tts_configured:
                    continue
                try:
                    audio_bytes = self._synthesize_gemini(
                        text,
                        language_hint=language_hint,
                    )
                    self.last_tts_backend = "Gemini voice"
                    self._write_tts_cache(cache_path, audio_bytes)
                    return audio_bytes
                except Exception as exc:
                    errors.append(f"gemini={type(exc).__name__}: {exc}")
                    if self.tts_backend == "gemini-only":
                        break

        detail = "; ".join(errors) or "no usable speech backend"
        raise AIServiceError(
            f"Spoken answer is unavailable ({detail}). The text answer remains readable."
        )

    def play_wav_bytes(self, audio_bytes: bytes) -> None:
        if not self.native_playback_available:
            raise AIServiceError("Native desktop audio playback is unavailable.")
        if not self._is_valid_wav(audio_bytes):
            raise AIServiceError("The spoken answer is not a valid WAV file.")
        try:
            import winsound

            winsound.PlaySound(
                bytes(audio_bytes),
                winsound.SND_MEMORY | winsound.SND_NODEFAULT,
            )
        except Exception as exc:
            raise AIServiceError(
                f"Native Windows playback failed: {type(exc).__name__}: {exc}"
            ) from exc
