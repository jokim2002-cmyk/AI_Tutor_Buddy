from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Callable, Sequence

import flet as ft
from flet.auth.providers import GoogleOAuthProvider

from cloud_auth_session import FirebaseSessionManager, OAuthTokenStore
from cloud_sync import (
    CloudSyncError,
    ConversationSyncService,
    FirebaseAuthREST,
    FirebaseConfig,
    FirestoreREST,
)
from conversation_store import ConversationStore, DeviceIdentityStore
from gyanverse_ui_helpers import mode_label, safe_text
from phase11_ai import AIServiceError, GyanVerseAIService
from phase11_core import (
    GeneratedTestPaper,
    GSEBSyllabusRepository,
    HomeworkAttachmentStore,
    LearningContextStore,
    LearningMode,
    Phase11Error,
    StudentLearningContext,
    TestPaperQuestionItem,
    VoiceState,
    canonicalize_installed_syllabus_context,
    detect_context_from_message,
    evaluate_test_paper,
    format_tutor_response,
    prepare_spoken_text,
    split_into_speech_chunks,
)
from tutor_engine import TutorEngine

try:
    import flet_audio as fta
except ImportError:  # optional extension; UI falls back to readable text
    fta = None

try:
    import flet_audio_recorder as far
except ImportError:  # optional extension; UI falls back to typing
    far = None


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
ASSETS_DIR = APP_DIR / "assets"
DATA_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)
ACTIVE_TEST_PAPERS_PATH = DATA_DIR / "active_test_papers.json"

# V1 commercial pilot scope:
# Only English medium is exposed. Gujarati can be added later after the English pilot succeeds.
GYANVERSE_V1_ALLOWED_MEDIUMS = ("English",)
GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES = ("English",)
GYANVERSE_V1_CLOUD_SYNC_ENABLED = False

NAV_ITEMS = (
    ("home", "Home", ft.Icons.HOME_OUTLINED, ft.Icons.HOME),
    ("tutor", "Tutor", ft.Icons.SCHOOL_OUTLINED, ft.Icons.SCHOOL),
    ("sync", "Daily Sync", ft.Icons.SYNC, ft.Icons.SYNC),
    ("homework", "Homework", ft.Icons.ASSIGNMENT_OUTLINED, ft.Icons.ASSIGNMENT),
    ("revision", "Revision", ft.Icons.REPLAY, ft.Icons.REPLAY),
    ("progress", "Progress", ft.Icons.INSIGHTS_OUTLINED, ft.Icons.INSIGHTS),
    ("syllabus", "Syllabus Coverage", ft.Icons.MENU_BOOK_OUTLINED, ft.Icons.MENU_BOOK),
    ("settings", "Settings", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS),
)

COLOR_PRIMARY = "#2563EB"
COLOR_PRIMARY_DARK = "#1E40AF"
COLOR_ACCENT = "#059669"
COLOR_BACKGROUND = "#F8F9FA"
COLOR_SURFACE = "#FFFFFF"
COLOR_BORDER = "#E2E8F0"
COLOR_TEXT = "#0F172A"
COLOR_MUTED = "#334155"
COLOR_USER = "#E0EBFF"
COLOR_TUTOR = "#FFFFFF"
COLOR_SUCCESS = "#059669"
COLOR_ERROR = "#DC2626"
COLOR_PANEL = "#F6F8FC"
COLOR_SOFT_BORDER = "#D7DEE8"
COLOR_TUTOR_BORDER = "#DDE5EF"
COLOR_USER_BORDER = "#B8CAFF"
COLOR_BANNER = "#ECFDF5"
COLOR_BANNER_BORDER = "#C7F2DF"

FAST_REPLY_DEADLINE_SECONDS = 15.0
SPOKEN_ANSWER_DEADLINE_SECONDS = 95.0
SPOKEN_PLAYBACK_DEADLINE_SECONDS = 300.0


def _wav_from_pcm(pcm: bytes, sample_rate: int = 44_100) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return output.getvalue()


def main(page: ft.Page) -> None:
    page.title = "GyanVerse Academy"
    page.padding = 0
    page.bgcolor = COLOR_PANEL
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=COLOR_PRIMARY, use_material3=True)
    try:
        page.window.width = 1180
        page.window.height = 760
        page.window.min_width = 360
        page.window.min_height = 600
    except Exception:
        pass

    context_store = LearningContextStore(DATA_DIR / "student_context.json")
    context = context_store.load()
    if context.medium.casefold() not in {item.casefold() for item in GYANVERSE_V1_ALLOWED_MEDIUMS}:
        context = context_store.save(
            replace(
                context,
                medium=GYANVERSE_V1_ALLOWED_MEDIUMS[0],
                preferred_language=GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES[0],
            )
        )
    syllabus_repo = GSEBSyllabusRepository(APP_DIR / "syllabus")
    canonical_context = canonicalize_installed_syllabus_context(context, syllabus_repo)
    if canonical_context != context:
        context = context_store.save(canonical_context)
    device_identity = DeviceIdentityStore(DATA_DIR / "device_identity.json").load_or_create()
    local_owner_id = device_identity.local_owner_id
    current_owner_id = local_owner_id
    conversation_store = ConversationStore(
        DATA_DIR / "conversations.db", device_id=device_identity.device_id
    )
    active_conversation = conversation_store.get_or_create_active(
        owner_id=local_owner_id,
        student_id=context.student_id,
        board=context.board,
        standard=context.standard,
        subject=context.current_subject,
        chapter=context.current_chapter,
    )
    attachment_store = HomeworkAttachmentStore(DATA_DIR / "homework_attachments")
    engine = TutorEngine(db_path=DATA_DIR / "ai_tutor.db")
    ai_service = GyanVerseAIService(syllabus_repository=syllabus_repo)
    session_id = active_conversation.conversation_id

    firebase_config = FirebaseConfig.from_env()
    firebase_auth = FirebaseAuthREST(firebase_config)
    firebase_sessions = FirebaseSessionManager(firebase_config, auth=firebase_auth)
    firestore = FirestoreREST(firebase_config)
    cloud_sync_service = ConversationSyncService(conversation_store, firestore)
    oauth_token_store = OAuthTokenStore(DATA_DIR / "google_oauth_token.enc")
    google_provider = (
        GoogleOAuthProvider(
            client_id=firebase_config.google_client_id,
            client_secret=firebase_config.google_client_secret,
            redirect_url=firebase_config.oauth_redirect_url,
        )
        if firebase_config.live_sync_ready
        else None
    )

    engine.ensure_student(
        student_id=context.student_id,
        name=context.name,
        grade=context.standard,
        board=context.board,
        preferred_language=context.preferred_language,
    )

    current_view = "tutor"
    voice_state = VoiceState.IDLE
    voice_capture_path: Path | None = None
    latest_tutor_answer = ""
    active_audio = None
    selected_attachments = []
    cloud_sync_busy = False

    initial_is_mobile = float(getattr(page, "width", 0) or 1180) < 700.0
    title_text = ft.Text(
        "Tutor",
        size=20 if initial_is_mobile else 24,
        weight=ft.FontWeight.BOLD,
        color=COLOR_TEXT,
    )
    context_text = ft.Text(
        context.context_label,
        size=11 if initial_is_mobile else 13,
        color=COLOR_MUTED,
        max_lines=1,
    )
    lesson_context_text: ft.Text | None = None
    status_text = ft.Text("Ready", size=13, color=COLOR_MUTED)
    cloud_status_text = ft.Text("Cloud: signed out", size=13, color=COLOR_MUTED)
    account_button = ft.IconButton(icon=ft.Icons.ACCOUNT_CIRCLE_OUTLINED, tooltip="Google account and cloud sync")
    new_chat_button = ft.IconButton(
        icon=ft.Icons.ADD,
        tooltip="Start new chat",
    )
    body = ft.Container(expand=True, padding=0, bgcolor=COLOR_PANEL)
    menu_button = ft.IconButton(icon=ft.Icons.MENU, tooltip="Open menu")

    def activate_owner(owner_id: str) -> None:
        nonlocal current_owner_id, active_conversation, session_id
        current_owner_id = str(owner_id or local_owner_id)
        active_conversation = conversation_store.get_or_create_active(
            owner_id=current_owner_id,
            student_id=context.student_id,
            board=context.board,
            standard=context.standard,
            subject=context.current_subject,
            chapter=context.current_chapter,
        )
        session_id = active_conversation.conversation_id

    def _active_test_papers_payload() -> dict[str, object]:
        try:
            if not ACTIVE_TEST_PAPERS_PATH.exists():
                return {}
            payload = json.loads(ACTIVE_TEST_PAPERS_PATH.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def save_active_test_paper(paper: GeneratedTestPaper | None) -> None:
        if paper is None:
            return
        try:
            payload = _active_test_papers_payload()
            payload[active_conversation.conversation_id] = asdict(paper)
            ACTIVE_TEST_PAPERS_PATH.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass

    def restore_active_test_paper() -> bool:
        ai_service._last_generated_test_paper = None
        try:
            raw = _active_test_papers_payload().get(active_conversation.conversation_id)
            if not isinstance(raw, dict):
                return False
            raw_questions = raw.get("questions")
            if not isinstance(raw_questions, list):
                return False

            question_fields = {field.name for field in fields(TestPaperQuestionItem)}
            questions = []
            for item in raw_questions:
                if not isinstance(item, dict):
                    continue
                question_payload = {
                    name: item[name]
                    for name in question_fields
                    if name in item
                }
                questions.append(TestPaperQuestionItem(**question_payload))
            if not questions:
                return False

            paper_fields = {field.name for field in fields(GeneratedTestPaper)}
            paper_payload = {
                name: raw[name]
                for name in paper_fields
                if name in raw
            }
            if (
                paper_payload.get("subject")
                and context.current_subject
                and str(paper_payload["subject"]).casefold() != context.current_subject.casefold()
            ):
                ai_service._last_generated_test_paper = None
                return False
            paper_payload["questions"] = questions
            ai_service._last_generated_test_paper = GeneratedTestPaper(**paper_payload)
            return True
        except Exception:
            ai_service._last_generated_test_paper = None
            return False


    def start_new_chat(_: object = None) -> None:
        nonlocal active_conversation, session_id, latest_tutor_answer, active_audio, selected_attachments
        ai_service.stop_playback()
        active_conversation = conversation_store.create_conversation(
            owner_id=current_owner_id,
            student_id=context.student_id,
            board=context.board,
            standard=context.standard,
            subject=context.current_subject,
            chapter=context.current_chapter,
            title="New conversation",
        )
        session_id = active_conversation.conversation_id
        latest_tutor_answer = ""
        active_audio = None
        ai_service._last_generated_test_paper = None
        selected_attachments = []
        status_text.value = "New chat started"
        show_view("tutor")

    def refresh_cloud_status(message: str | None = None, *, error: bool = False) -> None:
        if not GYANVERSE_V1_CLOUD_SYNC_ENABLED:
            label = "Cloud: disabled in English V1 pilot"
            cloud_status_text.value = label
            cloud_status_text.color = COLOR_MUTED
            account_button.icon = ft.Icons.ACCOUNT_CIRCLE_OUTLINED
            account_button.tooltip = label
            return

        session = firebase_sessions.session
        if message is not None:
            label = message
        elif session is not None:
            identity = session.display_name or session.email or "Google account"
            pending = conversation_store.pending_outbox_count(owner_id=session.uid)
            label = f"Cloud: {identity} • {pending} pending" if pending else f"Cloud: {identity} • synced"
        elif not firebase_config.live_sync_ready:
            label = "Cloud: setup required"
        else:
            label = "Cloud: signed out"
        cloud_status_text.value = label
        cloud_status_text.color = COLOR_ERROR if error else COLOR_MUTED
        account_button.icon = (
            ft.Icons.CLOUD_DONE if session is not None else ft.Icons.ACCOUNT_CIRCLE_OUTLINED
        )
        account_button.tooltip = label

    async def sync_cloud_now(*, show_result: bool = True, refresh_tutor: bool = True) -> None:
        nonlocal cloud_sync_busy
        if not GYANVERSE_V1_CLOUD_SYNC_ENABLED:
            if show_result:
                notify("Cloud sync is disabled in the English V1 pilot. Local tutor and local chat remain available.")
            return
        if cloud_sync_busy:
            return
        if firebase_sessions.session is None:
            if show_result:
                notify("Sign in with Google before cloud sync.", error=True)
            return
        cloud_sync_busy = True
        refresh_cloud_status("Cloud: syncing…")
        page.update()
        try:
            session = await asyncio.to_thread(firebase_sessions.current)
            pushed, pulled = await asyncio.to_thread(
                cloud_sync_service.sync_bidirectional, session=session
            )
            refresh_cloud_status()
            if refresh_tutor and (pulled.conversations_merged or pulled.messages_merged):
                activate_owner(session.uid)
                show_view("tutor")
            elif show_result:
                notify(
                    f"Cloud sync complete: {pushed.synced} uploaded, "
                    f"{pulled.messages_merged} messages downloaded."
                )
            else:
                page.update()
        except CloudSyncError as exc:
            refresh_cloud_status(f"Cloud sync unavailable • {exc.category}", error=True)
            if show_result:
                notify("Cloud sync could not complete. Local chat remains safe.", error=True)
            else:
                page.update()
        except Exception:
            refresh_cloud_status("Cloud sync unavailable", error=True)
            if show_result:
                notify("Cloud sync could not complete. Local chat remains safe.", error=True)
            else:
                page.update()
        finally:
            cloud_sync_busy = False

    async def cloud_sync_button_click(_: object = None) -> None:
        await sync_cloud_now()

    async def google_login_click(_: object = None) -> None:
        if not GYANVERSE_V1_CLOUD_SYNC_ENABLED:
            notify("Google sign-in is disabled in the English V1 pilot. Use the local tutor without signing in.")
            return
        if google_provider is None:
            missing = ", ".join(firebase_config.missing_live_sync_fields())
            notify(f"Google cloud setup is incomplete: {missing}", error=True)
            return
        refresh_cloud_status("Cloud: opening Google sign-in…")
        page.update()
        await page.login(google_provider, scope=["openid", "email", "profile"])

    async def google_login_completed(event: object) -> None:
        error = str(getattr(event, "error", "") or "").strip()
        if error:
            refresh_cloud_status("Cloud: Google sign-in failed", error=True)
            notify("Google sign-in did not complete.", error=True)
            return
        try:
            if page.auth is None:
                raise RuntimeError("Flet OAuth completed without an auth context.")
            oauth_token = await page.auth.get_token()
            access_token = str(oauth_token.access_token or "").strip()
            session = await asyncio.to_thread(
                firebase_sessions.exchange_google_access_token, access_token
            )
            token_json = str(oauth_token.to_json() or "")
            if oauth_token_store.enabled:
                await asyncio.to_thread(oauth_token_store.save, token_json)
            conversation_store.claim_local_owner(
                local_owner_id=local_owner_id, authenticated_owner_id=session.uid
            )
            activate_owner(session.uid)
            await sync_cloud_now(show_result=False, refresh_tutor=True)
            refresh_cloud_status()
            show_view("tutor")
        except CloudSyncError as exc:
            firebase_sessions.clear()
            refresh_cloud_status(f"Cloud sign-in failed • {exc.category}", error=True)
            notify("Google account connected, but Firebase sign-in failed.", error=True)
        except Exception as exc:
            firebase_sessions.clear()
            _frames = __import__("traceback").extract_tb(exc.__traceback__)
            _last = _frames[-1] if _frames else None
            _location = (
                f"{_last.filename}:{_last.lineno} in {_last.name}"
                if _last is not None
                else "unknown"
            )
            print(
                "GYANVERSE_GOOGLE_SIGNIN_ERROR "
                f"type={type(exc).__name__} location={_location}",
                flush=True,
            )
            refresh_cloud_status(
                f"Cloud sign-in failed â€¢ {type(exc).__name__}", error=True
            )
            notify("Google cloud sign-in could not complete.", error=True)

    def complete_logout() -> None:
        firebase_sessions.clear()
        oauth_token_store.clear()
        activate_owner(local_owner_id)
        status_text.value = "Ready"
        refresh_cloud_status()
        show_view("tutor")

    async def google_logout_click(_: object = None) -> None:
        oauth_token_store.clear()
        page.logout()

    def google_logout_completed(_: object = None) -> None:
        complete_logout()

    def update_context(new_context: StudentLearningContext, *, persist: bool = True) -> None:
        nonlocal context
        validated = canonicalize_installed_syllabus_context(new_context.validate(), syllabus_repo)
        meaningful_fields = (
            "student_id",
            "name",
            "board",
            "medium",
            "standard",
            "preferred_language",
            "current_subject",
            "current_chapter",
            "current_topic",
            "learning_mode",
            "onboarding_complete",
        )
        if all(getattr(context, field) == getattr(validated, field) for field in meaningful_fields):
            return
        identity_changed = any(
            getattr(context, field) != getattr(validated, field)
            for field in (
                "student_id",
                "name",
                "board",
                "medium",
                "standard",
                "preferred_language",
            )
        )
        lesson_scope_changed = any(
            getattr(context, field) != getattr(validated, field)
            for field in (
                "student_id",
                "board",
                "medium",
                "standard",
                "current_subject",
                "current_chapter",
            )
        )
        context = context_store.save(validated) if persist else validated
        if identity_changed:
            engine.ensure_student(
                student_id=context.student_id,
                name=context.name,
                grade=context.standard,
                board=context.board,
                preferred_language=context.preferred_language,
            )
        if lesson_scope_changed:
            activate_owner(current_owner_id)
            ai_service.reset_session()
            restore_active_test_paper()
        context_text.value = context.context_label
        if lesson_context_text is not None:
            lesson_context_text.value = context.context_label

    def notify(message: str, *, error: bool = False) -> None:
        status_text.value = message
        status_text.color = COLOR_ERROR if error else COLOR_MUTED
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message),
                bgcolor="#FFEDEA" if error else "#E8F7F3",
            )
        )
        page.update()

    def surface(content: ft.Control, *, padding: int = 16) -> ft.Container:
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=COLOR_SURFACE,
            border=ft.Border.all(1, COLOR_SOFT_BORDER),
            border_radius=12,
            shadow=ft.BoxShadow(
                blur_radius=14,
                spread_radius=0,
                color="#140F172A",
                offset=ft.Offset(0, 4),
            ),
        )

    def page_panel(title: str, subtitle: str, content: ft.Control) -> ft.Container:
        return ft.Container(
            expand=True,
            content=ft.Container(
                expand=True,
                padding=ft.Padding(left=18, top=14, right=18, bottom=14),
                content=ft.Column(
                    [
                        ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color=COLOR_TEXT),
                        ft.Text(subtitle, size=13, color=COLOR_MUTED),
                        content,
                    ],
                    expand=True,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
        )

    def metric(label: str, value: str, hint: str) -> ft.Container:
        return surface(
            ft.Column(
                [
                    ft.Text(label, size=13, color=COLOR_MUTED),
                    ft.Text(value, size=20, weight=ft.FontWeight.BOLD, color=COLOR_TEXT),
                    ft.Text(hint, size=12, color=COLOR_MUTED),
                ],
                spacing=3,
            ),
            padding=13,
        )

    def report_card(title: str, getter: Callable[[], str]) -> ft.Control:
        output = ft.Text("Tap refresh to load the latest report.", selectable=True, color=COLOR_TEXT, size=17)

        def refresh(_: object = None) -> None:
            try:
                output.value = safe_text(getter())
                status_text.value = f"{title} refreshed"
            except Exception as exc:
                output.value = f"Unable to load report: {type(exc).__name__}: {exc}"
            page.update()

        return surface(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=COLOR_TEXT),
                            ft.Container(expand=True),
                            ft.IconButton(ft.Icons.REFRESH, tooltip="Refresh", on_click=refresh),
                        ]
                    ),
                    output,
                ],
                spacing=8,
            )
        )

    def open_profile_dialog(_: object = None, *, first_use: bool = False) -> None:
        allowed_subjects = {
            "English",
            "Mathematics",
            "Science",
            "Science & Technology",
            "Social Science",
        }
        dialog_viewport_width = float(getattr(page, "width", 0) or 560)
        dialog_viewport_height = float(getattr(page, "height", 0) or 760)
        dialog_is_mobile = dialog_viewport_width < 700.0
        dialog_width = max(300.0, min(560.0, dialog_viewport_width - 44.0)) if dialog_is_mobile else 560.0
        dialog_height = max(420.0, min(500.0, dialog_viewport_height - 230.0)) if dialog_is_mobile else 560.0
        profile_field_width = max(260.0, dialog_width - 32.0)
        compact_field_height = 50 if dialog_is_mobile else None

        name_field = ft.TextField(
            label="Student name",
            value=context.name,
            width=profile_field_width,
            dense=dialog_is_mobile,
            height=compact_field_height,
            visible=not dialog_is_mobile,
        )
        board_field = ft.Dropdown(
            label="Board",
            width=140 if dialog_is_mobile else 150,
            height=compact_field_height,
            dense=dialog_is_mobile,
            value=context.board if context.board in {"GSEB", "CBSE"} else "GSEB",
            options=[ft.dropdown.Option(item) for item in ("GSEB", "CBSE")],
        )
        medium_field = ft.Dropdown(
            label="Medium",
            width=profile_field_width,
            height=compact_field_height,
            dense=dialog_is_mobile,
            value=context.medium if context.medium in GYANVERSE_V1_ALLOWED_MEDIUMS else GYANVERSE_V1_ALLOWED_MEDIUMS[0],
            options=[ft.dropdown.Option(item) for item in GYANVERSE_V1_ALLOWED_MEDIUMS],
            visible=False,
        )
        standard_field = ft.Dropdown(
            label="Standard",
            width=116 if dialog_is_mobile else 120,
            height=compact_field_height,
            dense=dialog_is_mobile,
            value=str(context.standard) if 1 <= context.standard <= 10 else "7",
            options=[ft.dropdown.Option(str(item)) for item in range(1, 11)],
        )
        language_field = ft.Dropdown(
            label="Tutor language",
            width=profile_field_width,
            height=compact_field_height,
            dense=dialog_is_mobile,
            value=context.preferred_language if context.preferred_language in GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES else GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES[0],
            options=[ft.dropdown.Option(item) for item in GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES],
            visible=False,
        )

        locked_scope_text = ft.Text(
            "English medium is locked for V1 pilot.",
            size=10,
            color=COLOR_MUTED,
            visible=dialog_is_mobile,
        )
        selected_lesson_hint = ft.Text(
            "",
            size=10 if dialog_is_mobile else 11,
            color=COLOR_MUTED,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            visible=dialog_is_mobile,
        )
        subject_field = ft.Dropdown(
            label="Subject",
            width=profile_field_width,
            height=compact_field_height,
            dense=dialog_is_mobile,
        )
        chapter_field = ft.Dropdown(
            label="Chapter",
            width=profile_field_width,
            height=compact_field_height,
            dense=dialog_is_mobile,
        )
        topic_field = ft.Dropdown(
            label="Topic",
            width=profile_field_width,
            height=compact_field_height,
            dense=dialog_is_mobile,
        )
        package_status = ft.Text(size=10, color=COLOR_MUTED, max_lines=2)

        def matching_syllabi() -> list[object]:
            board = board_field.value or "GSEB"
            medium = medium_field.value or GYANVERSE_V1_ALLOWED_MEDIUMS[0]
            standard = int(standard_field.value or 7)
            return [
                item
                for item in syllabus_repo.all(board=board)
                if item.medium.casefold() == medium.casefold()
                and item.standard == standard
                and item.subject in allowed_subjects
            ]

        def selected_syllabus() -> object | None:
            selected = subject_field.value or ""
            return next(
                (item for item in matching_syllabi() if item.subject == selected),
                None,
            )

        def refresh_topics(*, preserve: bool = True) -> None:
            syllabus = selected_syllabus()
            chapter = next(
                (
                    item
                    for item in (syllabus.chapters if syllabus is not None else ())
                    if item.title == (chapter_field.value or "")
                ),
                None,
            )
            old_value = topic_field.value if preserve else ""
            topic_titles = [item.title for item in (chapter.topics if chapter is not None else ())]
            topic_field.options = [ft.dropdown.Option(item) for item in topic_titles]
            topic_field.value = old_value if old_value in topic_titles else (topic_titles[0] if topic_titles else None)
            selected_lesson_hint.value = (
                f"Selected chapter: {chapter_field.value or 'Not selected'}\n"
                f"Selected topic: {topic_field.value or 'Not selected'}"
            )

        def refresh_chapters(*, preserve: bool = True) -> None:
            syllabus = selected_syllabus()
            old_value = chapter_field.value if preserve else ""
            chapter_titles = [item.title for item in (syllabus.chapters if syllabus is not None else ())]
            chapter_field.options = [ft.dropdown.Option(item) for item in chapter_titles]
            chapter_field.value = old_value if old_value in chapter_titles else (chapter_titles[0] if chapter_titles else None)
            refresh_topics(preserve=preserve)

        def refresh_subjects(*, preserve: bool = True) -> None:
            installed = matching_syllabi()
            subjects = sorted({item.subject for item in installed})
            old_value = subject_field.value if preserve else ""
            subject_field.options = [ft.dropdown.Option(item) for item in subjects]
            subject_field.value = old_value if old_value in subjects else (subjects[0] if subjects else None)
            package_status.value = (
                f"{len(subjects)} installed subject package(s) available for this selection."
                if subjects
                else "No installed syllabus package is available for this board, medium and standard."
            )
            package_status.color = COLOR_MUTED if subjects else COLOR_ERROR
            refresh_chapters(preserve=preserve)

        def profile_scope_changed(_: object = None) -> None:
            refresh_subjects(preserve=False)
            page.update()

        def subject_changed(_: object = None) -> None:
            refresh_chapters(preserve=False)
            page.update()

        def chapter_changed(_: object = None) -> None:
            refresh_topics(preserve=False)
            page.update()

        board_field.on_change = profile_scope_changed
        board_field.on_select = profile_scope_changed
        medium_field.on_change = profile_scope_changed
        medium_field.on_select = profile_scope_changed
        standard_field.on_change = profile_scope_changed
        standard_field.on_select = profile_scope_changed
        subject_field.on_change = subject_changed
        subject_field.on_select = subject_changed
        chapter_field.on_change = chapter_changed
        chapter_field.on_select = chapter_changed
        subject_field.value = context.current_subject
        chapter_field.value = context.current_chapter
        topic_field.value = context.current_topic
        refresh_subjects(preserve=True)

        def save_profile(_: object = None) -> None:
            try:
                if not subject_field.value or not chapter_field.value or not topic_field.value:
                    raise Phase11Error(
                        "Select an installed subject, chapter and topic before continuing."
                    )
                update_context(
                    replace(
                        context,
                        name=(name_field.value or "Student").strip(),
                        board=board_field.value or "GSEB",
                        medium=medium_field.value or GYANVERSE_V1_ALLOWED_MEDIUMS[0],
                        standard=int(standard_field.value or 7),
                        preferred_language=language_field.value or GYANVERSE_V1_ALLOWED_TUTOR_LANGUAGES[0],
                        current_subject=subject_field.value,
                        current_chapter=chapter_field.value,
                        current_topic=topic_field.value,
                        onboarding_complete=True,
                    )
                )
                activate_owner(current_owner_id)
                page.pop_dialog()
                show_view(current_view)
                notify("Student profile saved")
            except (ValueError, Phase11Error) as exc:
                notify(str(exc), error=True)

        dialog = ft.AlertDialog(
            modal=first_use,
            title=ft.Text("Set up your personal tutor", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=dialog_width,
                height=dialog_height,
                content=ft.Column(
                    [
                        name_field,
                        ft.Row([board_field, medium_field, standard_field], spacing=10, wrap=True),
                        locked_scope_text,
                        language_field,
                        ft.Divider(height=6),
                        ft.Text("Current school lesson", size=15, weight=ft.FontWeight.BOLD),
                        package_status,
                        selected_lesson_hint,
                        subject_field,
                        chapter_field,
                        topic_field,
                    ],
                    tight=False,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: page.pop_dialog())
                if not first_use
                else ft.Container(),
                ft.ElevatedButton("Save and continue", on_click=save_profile),
            ],
            scrollable=True,
        )
        page.show_dialog(dialog)

    def build_home() -> ft.Control:
        today = engine.format_today_summary(context.student_id)
        return page_panel(
            f"Hi {context.name}",
            "Continue from the chapter your school is teaching now.",
            ft.Column(
                [
                    ft.ResponsiveRow(
                        [
                            ft.Container(metric("Board", context.board, context.medium), col={"xs": 6, "md": 3}),
                            ft.Container(metric("Standard", str(context.standard), context.preferred_language), col={"xs": 6, "md": 3}),
                            ft.Container(metric("Subject", context.current_subject or "Not selected", "Current class context"), col={"xs": 6, "md": 3}),
                            ft.Container(metric("Mode", mode_label(context.learning_mode), "Hint-first tutoring"), col={"xs": 6, "md": 3}),
                        ],
                        spacing=10,
                        run_spacing=10,
                    ),
                    surface(
                        ft.Column(
                            [
                                ft.Text("Current school context", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(context.context_label, color=COLOR_TEXT),
                                ft.Row(
                                    [
                                        ft.ElevatedButton("Ask Tutor", icon=ft.Icons.CHAT_BUBBLE_OUTLINE, on_click=lambda _: show_view("tutor")),
                                        ft.OutlinedButton("Update chapter", icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _: show_view("sync")),
                                    ],
                                    wrap=True,
                                ),
                            ],
                            spacing=10,
                        )
                    ),
                    surface(
                        ft.Column(
                            [
                                ft.Text("Today", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(safe_text(today), selectable=True),
                            ],
                            spacing=8,
                        )
                    ),
                ],
                spacing=12,
            ),
        )

    def build_sync() -> ft.Control:
        subject = ft.TextField(label="Subject", value=context.current_subject)
        chapter = ft.TextField(label="Chapter", value=context.current_chapter)
        topic = ft.TextField(label="What was taught today?", value=context.current_topic, multiline=True, min_lines=2, max_lines=5)
        result = ft.Text(color=COLOR_SUCCESS)

        def save(_: object = None) -> None:
            try:
                values = [(subject.value or "").strip(), (chapter.value or "").strip(), (topic.value or "").strip()]
                if not all(values):
                    raise Phase11Error("Subject, chapter and today's topic are required.")
                saved = engine.record_daily_sync(
                    student_id=context.student_id,
                    subject=values[0],
                    chapter=values[1],
                    topic=values[2],
                )
                update_context(
                    replace(
                        context,
                        current_subject=saved["subject"],
                        current_chapter=saved["chapter"],
                        current_topic=saved["topic"],
                    )
                )
                result.value = f"Saved: {saved['subject']} → {saved['chapter']} → {saved['topic']}"
                notify("Today's class context saved")
            except Exception as exc:
                notify(str(exc), error=True)
            page.update()

        return page_panel(
            "Daily Class Sync",
            "Tell GyanVerse what happened in school so the tutor can continue from there.",
            surface(ft.Column([subject, chapter, topic, ft.ElevatedButton("Save today's learning", icon=ft.Icons.SAVE, on_click=save), result], spacing=12)),
        )

    def build_homework() -> ft.Control:
        subject = ft.TextField(label="Subject", value=context.current_subject or "Mathematics")
        chapter = ft.TextField(label="Chapter", value=context.current_chapter)
        count = ft.Dropdown(label="Questions", value="5", options=[ft.dropdown.Option(str(n)) for n in range(1, 11)])
        output = ft.Text(selectable=True)

        def generate(_: object = None) -> None:
            try:
                homework = engine.generate_homework(
                    student_id=context.student_id,
                    subject=subject.value or "",
                    chapter=chapter.value or "",
                    question_count=int(count.value or 5),
                )
                lines = [f"Homework ID: {homework['homework_id']}", f"Difficulty: {homework['difficulty']}", ""]
                lines.extend(f"{item['number']}. {item['question']}" for item in homework["questions"])
                output.value = "\n".join(lines)
                notify("Adaptive homework generated")
            except Exception as exc:
                output.value = f"Unable to generate homework: {exc}"
                notify(str(exc), error=True)
            page.update()

        history = attachment_store.list_student(context.student_id)
        history_controls: list[ft.Control] = []
        for item in reversed(history[-12:]):
            def remove(_: object = None, attachment_id: str = item.attachment_id) -> None:
                attachment_store.delete(attachment_id, student_id=context.student_id)
                show_view("homework")
                notify("Homework file deleted")

            history_controls.append(
                surface(
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.IMAGE_OUTLINED if item.is_image else ft.Icons.DESCRIPTION_OUTLINED, color=COLOR_PRIMARY),
                            ft.Column([ft.Text(item.original_name, weight=ft.FontWeight.BOLD), ft.Text(f"{item.display_size} • saved locally", size=10, color=COLOR_MUTED)], expand=True, spacing=2),
                            ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Delete local file", on_click=remove),
                        ]
                    ),
                    padding=10,
                )
            )
        if not history_controls:
            history_controls.append(ft.Text("No submitted homework files yet.", color=COLOR_MUTED))

        return page_panel(
            "Homework Studio",
            "Generate practice or attach homework pages in Tutor mode for hint-first review.",
            ft.Column(
                [
                    surface(
                        ft.Column(
                            [
                                ft.ResponsiveRow(
                                    [
                                        ft.Container(subject, col={"xs": 12, "md": 5}),
                                        ft.Container(chapter, col={"xs": 12, "md": 5}),
                                        ft.Container(count, col={"xs": 12, "md": 2}),
                                    ]
                                ),
                                ft.ElevatedButton("Generate adaptive homework", icon=ft.Icons.AUTO_AWESOME, on_click=generate),
                                output,
                            ],
                            spacing=12,
                        )
                    ),
                    ft.Text("Local homework history", size=17, weight=ft.FontWeight.BOLD),
                    ft.Column(history_controls, spacing=8),
                ],
                spacing=12,
            ),
        )

    def build_reports(kind: str) -> ft.Control:
        if kind == "revision":
            return page_panel(
                "Revision Centre",
                "Topics are prioritised using learning evidence and spaced revision.",
                ft.Column(
                    [
                        report_card("Revision queue", lambda: engine.format_revision_queue(context.student_id)),
                        report_card("Misconception patterns", lambda: engine.format_misconceptions(context.student_id)),
                    ],
                    spacing=12,
                ),
            )
        return page_panel(
            "Progress",
            "Evidence-based progress without permanent labels.",
            ft.Column(
                [
                    report_card("Progress summary", lambda: engine.format_progress(context.student_id)),
                    report_card("Today's summary", lambda: engine.format_today_summary(context.student_id)),
                ],
                spacing=12,
            ),
        )

    def build_syllabus() -> ft.Control:
        coverage = syllabus_repo.overall_coverage()
        installed = syllabus_repo.all()

        async def import_syllabus(_: object = None) -> None:
            try:
                files = await ft.FilePicker().pick_files(
                    dialog_title="Import validated GSEB/CBSE syllabus JSON",
                    allow_multiple=False,
                    with_data=True,
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["json"],
                )
                if not files:
                    status_text.value = "Syllabus import cancelled"
                    page.update()
                    return
                picked = files[0]
                raw = picked.bytes
                if raw is None and getattr(picked, "path", None):
                    raw = Path(picked.path).read_bytes()
                if raw is None:
                    raise Phase11Error("Unable to read the selected syllabus file.")
                payload = json.loads(raw.decode("utf-8-sig"))
                syllabus = syllabus_repo.install_payload(payload)
                notify(
                    f"Installed: {syllabus.board} {syllabus.medium} Std {syllabus.standard} {syllabus.subject}"
                )
                show_view("syllabus")
            except (UnicodeDecodeError, json.JSONDecodeError, Phase11Error) as exc:
                notify(f"Syllabus rejected: {exc}", error=True)
            except Exception as exc:
                notify(f"Syllabus import failed: {type(exc).__name__}: {exc}", error=True)
        installed_controls: list[ft.Control] = []
        for syllabus in installed:
            item_coverage = syllabus.coverage()
            installed_controls.append(
                surface(
                    ft.Column(
                        [
                            ft.Text(f"{syllabus.board} • {syllabus.medium} • Std {syllabus.standard} • {syllabus.subject}", weight=ft.FontWeight.BOLD),
                            ft.Text(f"{syllabus.textbook} • Edition {syllabus.source.edition}", size=11, color=COLOR_MUTED),
                            ft.Text(
                                f"Structured topics: {item_coverage['topics']} • Content coverage: {item_coverage['coverage_percent']}% • Official coverage: {item_coverage['official_coverage_percent']}%",
                                size=11,
                            ),
                        ],
                        spacing=4,
                    )
                )
            )
        if not installed_controls:
            installed_controls.append(
                surface(
                    ft.Text(
                        "The validated syllabus schema/importer is ready, but no official textbook dataset is installed yet. The app will not pretend that AI-generated material is official.",
                        color=COLOR_MUTED,
                    )
                )
            )
        coverage_cards: list[ft.Control] = [
            ft.Container(
                content=metric(
                    "Installed syllabi",
                    str(coverage["syllabi"]),
                    "Validated JSON packages",
                ),
                width=210,
            ),
            ft.Container(
                content=metric(
                    "Topics",
                    str(coverage["topics"]),
                    "Structured hierarchy",
                ),
                width=210,
            ),
            ft.Container(
                content=metric(
                    "Content coverage",
                    f"{coverage['coverage_percent']}%",
                    "Any validated content",
                ),
                width=210,
            ),
            ft.Container(
                content=metric(
                    "Official coverage",
                    f"{coverage['official_coverage_percent']}%",
                    "Official-source only",
                ),
                width=210,
            ),
        ]
        coverage_grid = ft.Row(
            controls=coverage_cards,
            wrap=True,
            spacing=10,
            run_spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        installed_packages = ft.Column(
            controls=installed_controls,
            spacing=8,
            tight=True,
        )
        syllabus_content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.ElevatedButton(
                            "Import validated JSON",
                            icon=ft.Icons.UPLOAD_FILE_OUTLINED,
                            on_click=import_syllabus,
                        ),
                        ft.Text(
                            "Only GSEB and CBSE packages with source, edition and content-origin metadata are accepted.",
                            size=10,
                            color=COLOR_MUTED,
                        ),
                    ],
                    wrap=True,
                    spacing=10,
                    run_spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                coverage_grid,
                ft.Text(
                    "Installed syllabus packages",
                    size=15,
                    weight=ft.FontWeight.BOLD,
                    color=COLOR_TEXT,
                ),
                installed_packages,
            ],
            spacing=12,
            tight=True,
        )
        return page_panel(
            "Syllabus Coverage",
            "Official sources and AI-generated practice remain clearly separated.",
            syllabus_content,
        )

    def build_settings() -> ft.Control:
        ai_status = "Configured" if ai_service.configured else "Not configured — typing and offline tutor fallback remain available"
        voice_extension = ai_service.transcription_backend if far is not None else "Recorder extension missing — typing fallback"
        return page_panel(
            "Settings & Privacy",
            "Student context and homework files stay local unless the student submits them to the configured AI service.",
            ft.Column(
                [
                    surface(
                        ft.Column(
                            [
                                ft.ListTile(
                                    leading=ft.Icon(ft.Icons.PERSON_OUTLINE),
                                    title=ft.Text(context.name),
                                    subtitle=ft.Text(context.context_label),
                                    trailing=ft.IconButton(ft.Icons.EDIT_OUTLINED, on_click=open_profile_dialog),
                                ),
                                ft.Divider(),
                                ft.Text(f"AI service: {ai_status}"),
                                ft.Text(f"Voice recorder: {voice_extension}"),
                                ft.Text(f"Local database: {engine.db_path}", size=10, color=COLOR_MUTED),
                            ],
                            spacing=8,
                        )
                    ),
                    surface(
                        ft.Column(
                            [
                                ft.Text("Google account & cloud sync (future)", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(cloud_status_text.value, color=cloud_status_text.color),
                                ft.Text(
                                    "English V1 pilot is local-first. Google sign-in is disabled until cloud setup is production-ready.",
                                    size=11,
                                    color=COLOR_MUTED,
                                ),
                                ft.Text(
                                    "No Google account is required for this pilot APK.",
                                    size=10,
                                    color=COLOR_MUTED,
                                ),
                                ft.Row(
                                    [
                                        ft.ElevatedButton(
                                            "Sign in with Google",
                                            icon=ft.Icons.LOGIN,
                                            on_click=google_login_click,
                                            disabled=firebase_sessions.session is not None,
                                        ),
                                        ft.OutlinedButton(
                                            "Sync now",
                                            icon=ft.Icons.SYNC,
                                            on_click=cloud_sync_button_click,
                                            disabled=firebase_sessions.session is None,
                                        ),
                                        ft.TextButton(
                                            "Sign out",
                                            icon=ft.Icons.LOGOUT,
                                            on_click=google_logout_click,
                                            disabled=firebase_sessions.session is None,
                                        ),
                                    ],
                                    wrap=True,
                                    visible=GYANVERSE_V1_CLOUD_SYNC_ENABLED,
                                ),
                            ],
                            spacing=8,
                        )
                    ),
                    surface(
                        ft.Column(
                            [
                                ft.Text("Privacy controls", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text("• Attached homework is copied into local app storage."),
                                ft.Text("• Files can be deleted from Homework History."),
                                ft.Text("• API keys are read from .env and must never be committed."),
                                ft.Text("• Missing syllabus content is shown as missing, not invented as official."),
                            ],
                            spacing=6,
                        )
                    ),
                ],
                spacing=12,
            ),
        )

    def build_tutor() -> ft.Control:
        nonlocal selected_attachments, latest_tutor_answer, lesson_context_text
        viewport_width = float(getattr(page, "width", 0) or 1180)
        is_mobile = viewport_width < 700.0
        shared_conversation_width = max(300.0, viewport_width - 24.0) if is_mobile else max(340.0, min(1320.0, viewport_width - 48.0))
        transcript_bottom_spacer = ft.Container(height=20 if is_mobile else 24)
        transcript = ft.Column(
            expand=True,
            spacing=8 if is_mobile else 12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
            auto_scroll=True,
            auto_scroll_animation=0,
            controls=[transcript_bottom_spacer],
        )
        transcript_surface = ft.Container(
            content=transcript,
            expand=True,
            padding=ft.Padding(left=4 if is_mobile else 8, top=4 if is_mobile else 8, right=4 if is_mobile else 8, bottom=4 if is_mobile else 8),
            bgcolor=COLOR_PANEL,
        )
        composer = ft.TextField(
            hint_text="Ask a textbook question from the selected chapter...",
            multiline=True,
            min_lines=1,
            max_lines=4,
            shift_enter=True,
            border=ft.InputBorder.NONE,
            bgcolor=COLOR_SURFACE,
            filled=True,
            dense=True,
            content_padding=ft.Padding(left=0, top=4, right=0, bottom=4),
            text_size=15 if is_mobile else 16,
        )
        composer_slot = ft.Container(content=composer, expand=True)
        mode_dropdown = ft.Dropdown(
            value=context.learning_mode,
            width=136 if is_mobile else 140,
            dense=True,
            text_size=12 if is_mobile else 13,
            options=[
                ft.dropdown.Option(LearningMode.EXPLAIN.value, "Answer"),
                ft.dropdown.Option(LearningMode.HOMEWORK.value, "Homework"),
                ft.dropdown.Option(LearningMode.REVISION.value, "Revision"),
                ft.dropdown.Option(LearningMode.EXAM.value, "Test / Exam"),
            ],
        )
        attachment_preview = ft.Row(
            wrap=False,
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            height=28,
            visible=False,
        )
        busy = ft.ProgressRing(width=16, height=16, visible=False)
        attach_button = ft.IconButton(
            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            icon_color=COLOR_PRIMARY,
            icon_size=22,
            padding=4,
            tooltip="Attach photo, PDF or document",
        )
        send_button = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_color=COLOR_PRIMARY,
            icon_size=22,
            padding=4,
            tooltip="Send",
        )
        mic_button = ft.IconButton(
            icon=ft.Icons.MIC_NONE_ROUNDED,
            icon_color=COLOR_PRIMARY,
            icon_size=22,
            padding=4,
            tooltip="Record voice",
        )
        speak_button = ft.IconButton(
            icon=ft.Icons.VOLUME_UP_OUTLINED,
            icon_size=21,
            padding=4,
            tooltip="Read last tutor answer",
            disabled=True,
        )

        def play_answer_audio(answer_text: str, voice_status_ctrl: ft.Text | None = None) -> None:
            nonlocal voice_state
            if not answer_text:
                return

            ai_service.stop_playback()
            if hasattr(ai_service, "_stop_playback_event"):
                ai_service._stop_playback_event.clear()

            chunks = split_into_speech_chunks(answer_text, max_chars=280)
            if not chunks:
                if voice_status_ctrl:
                    voice_status_ctrl.value = "No spoken content available"
                    try:
                        page.update()
                    except Exception:
                        pass
                return

            try:
                voice_state = VoiceState.PROCESSING
                for idx, chunk in enumerate(chunks, start=1):
                    if hasattr(ai_service, "_stop_playback_event") and ai_service._stop_playback_event.is_set():
                        break

                    if voice_status_ctrl:
                        voice_status_ctrl.value = f"Preparing natural voice {idx}/{len(chunks)}"
                        try:
                            page.update()
                        except Exception:
                            pass

                    audio_bytes: bytes | None = None
                    try:
                        audio_bytes = ai_service.synthesize(
                            chunk,
                            language_hint=context.preferred_language,
                        )
                    except Exception:
                        # Retry once with smaller chunk split if chunk fails or times out
                        if len(chunk) > 120:
                            mid = len(chunk) // 2
                            sp = chunk.rfind(" ", 0, mid + 20)
                            if sp <= 0:
                                sp = mid
                            s1 = chunk[:sp].strip()
                            s2 = chunk[sp:].strip()
                            pcm_parts: list[bytes] = []
                            if s1:
                                try:
                                    b1 = ai_service.synthesize(s1, language_hint=context.preferred_language)
                                    if b1 and b1.startswith(b"RIFF") and len(b1) > 44:
                                        pcm_parts.append(b1[44:])
                                except Exception:
                                    pass
                            if s2:
                                try:
                                    b2 = ai_service.synthesize(s2, language_hint=context.preferred_language)
                                    if b2 and b2.startswith(b"RIFF") and len(b2) > 44:
                                        pcm_parts.append(b2[44:])
                                except Exception:
                                    pass
                            if pcm_parts:
                                from phase11_ai import pcm_to_wav_bytes
                                audio_bytes = pcm_to_wav_bytes(b"".join(pcm_parts))

                    if hasattr(ai_service, "_stop_playback_event") and ai_service._stop_playback_event.is_set():
                        break

                    if not audio_bytes or not audio_bytes.startswith(b"RIFF") or b"WAVE" not in audio_bytes[:16]:
                        if voice_status_ctrl:
                            voice_status_ctrl.value = f"Natural voice skipped part {idx}/{len(chunks)}"
                            try:
                                page.update()
                            except Exception:
                                pass
                        continue

                    ai_service.play_wav_bytes(audio_bytes)
                    voice_state = VoiceState.PLAYING
                    if voice_status_ctrl:
                        voice_status_ctrl.value = f"Playing natural voice {idx}/{len(chunks)}"
                        try:
                            page.update()
                        except Exception:
                            pass

                    duration = 3.0
                    try:
                        duration = max(0.5, ai_service._parse_wav_duration(audio_bytes))
                    except Exception:
                        pass

                    waited = 0.0
                    while waited < duration:
                        if hasattr(ai_service, "_stop_playback_event") and ai_service._stop_playback_event.is_set():
                            break
                        time.sleep(0.05)
                        waited += 0.05

                if voice_status_ctrl:
                    if hasattr(ai_service, "_stop_playback_event") and ai_service._stop_playback_event.is_set():
                        voice_status_ctrl.value = "Audio stopped"
                    else:
                        voice_status_ctrl.value = "Ready"

            except Exception:
                voice_state = VoiceState.ERROR
                if voice_status_ctrl:
                    voice_status_ctrl.value = "Natural voice unavailable • Tap Play to retry"
            finally:
                if voice_state != VoiceState.ERROR:
                    voice_state = VoiceState.IDLE
                try:
                    page.update()
                except Exception:
                    pass

        def stop_answer_audio(voice_status_ctrl: ft.Text | None = None) -> None:
            nonlocal voice_state
            ai_service.stop_playback()
            voice_state = VoiceState.IDLE
            if voice_status_ctrl:
                voice_status_ctrl.value = "Audio stopped"
            page.update()

        async def prefetch_voice(answer_text: str, bubble_id: str, voice_status_ctrl: ft.Text) -> None:
            try:
                await asyncio.to_thread(
                    ai_service.synthesize,
                    answer_text,
                    language_hint=context.preferred_language,
                    answer_id=bubble_id,
                )
                m = ai_service.last_tts_metrics
                if m.success:
                    if m.cache_hit:
                        voice_status_ctrl.value = f"Natural voice ready • {m.selected_voice} • cached"
                    else:
                        prep_sec = m.total_prepare_ms / 1000.0
                        voice_status_ctrl.value = f"Natural voice ready • {m.selected_voice} • {prep_sec:.1f}s"
                else:
                    voice_status_ctrl.value = "Natural voice failed • Tap Play to retry"
            except Exception:
                voice_status_ctrl.value = "Natural voice failed • Tap Play to retry"
            finally:
                page.update()

        def create_tutor_voice_controls(answer_text: str, message_id: str) -> tuple[ft.Row, ft.Text]:
            voice_status_control = ft.Text("", visible=False)

            def copy_full_answer_to_clipboard(full_text: str) -> bool:
                text_to_copy = str(full_text or "")
                if not text_to_copy:
                    return False
                if os.name == "nt":
                    try:
                        subprocess.run(
                            ["powershell.exe", "-NoProfile", "-Command", "[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false); [Console]::In.ReadToEnd() | Set-Clipboard"],
                            input=text_to_copy,
                            text=True,
                            encoding="utf-8",
                            timeout=5,
                            check=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        return True
                    except Exception:
                        pass
                try:
                    if hasattr(page, "set_clipboard") and callable(page.set_clipboard):
                        page.set_clipboard(text_to_copy)
                        return True
                except Exception:
                    pass
                return False

            def copy_answer(_: object = None) -> None:
                try:
                    if not copy_full_answer_to_clipboard(answer_text):
                        raise RuntimeError("Clipboard unavailable")
                    btn_copy.icon = ft.Icons.CHECK
                    btn_copy.icon_color = COLOR_SUCCESS
                    btn_copy.tooltip = "Copied!"
                    try:
                        page.update()
                    except Exception:
                        pass
                except Exception:
                    try:
                        page.update()
                    except Exception:
                        pass

            btn_copy = ft.IconButton(
                icon=ft.Icons.COPY,
                icon_size=16,
                padding=2,
                tooltip="Copy answer to clipboard",
                on_click=copy_answer,
            )

            controls_row = ft.Row(
                [btn_copy],
                spacing=2,
                alignment=ft.MainAxisAlignment.END,
            )
            return controls_row, voice_status_control

        def persist_message(
            role: str,
            text: str,
            *,
            message_id: str | None = None,
            backend: str = "",
        ):
            return conversation_store.append_message(
                conversation_id=active_conversation.conversation_id,
                owner_id=current_owner_id,
                student_id=context.student_id,
                role=role,
                text=text,
                language=context.preferred_language,
                board=context.board,
                standard=context.standard,
                subject=context.current_subject,
                chapter=context.current_chapter,
                backend=backend,
                message_id=message_id,
            )

        def add_message(
            role: str,
            text: str,
            *,
            error: bool = False,
            persist: bool = True,
            message_id: str | None = None,
            backend: str = "",
        ) -> str | None:
            is_student = role == "student"
            saved_message = None
            if persist and not error and role in {"student", "tutor"}:
                saved_message = persist_message(
                    role, text, message_id=message_id, backend=backend
                )
            resolved_message_id = (
                saved_message.message_id
                if saved_message is not None
                else message_id or f"msg_{time.time_ns()}"
            )
            viewport_w = float(getattr(page, "width", 0) or 1180)
            is_mobile_screen = viewport_w < 700.0
            shared_w = max(300.0, viewport_w - 24.0) if is_mobile_screen else max(340.0, min(1320.0, viewport_w - 48.0))
            target_bubble_width = max(280.0, shared_w - 12.0) if is_mobile_screen else max(320.0, min(860.0 if is_student else 1040.0, shared_w - 40.0))
            font_size = 15 if is_mobile_screen else 17

            message_controls: list[ft.Control] = [
                ft.Text(
                    "You" if is_student else "GyanVerse Tutor",
                    size=11 if is_mobile_screen else 12,
                    weight=ft.FontWeight.BOLD,
                    color=COLOR_PRIMARY if is_student else COLOR_SUCCESS,
                ),
                ft.Text(text, selectable=True, color=COLOR_ERROR if error else COLOR_TEXT, size=font_size),
            ]
            if not is_student and not error:
                controls_row, _ = create_tutor_voice_controls(text, resolved_message_id)
                message_controls.append(controls_row)

            bubble = ft.Container(
                content=ft.Column(
                    message_controls,
                    spacing=4 if is_mobile_screen else 6,
                ),
                bgcolor=COLOR_USER if is_student else COLOR_TUTOR,
                border=ft.Border.all(1, COLOR_USER_BORDER if is_student else COLOR_TUTOR_BORDER),
                border_radius=ft.BorderRadius.only(
                    top_left=14 if is_mobile_screen else 16,
                    top_right=14 if is_mobile_screen else 16,
                    bottom_left=14 if (is_mobile_screen and is_student) else (16 if is_student else 4),
                    bottom_right=4 if is_student else (14 if is_mobile_screen else 16),
                ),
                padding=ft.Padding(left=12, top=10, right=12, bottom=10) if is_mobile_screen else ft.Padding(left=18, top=16, right=18, bottom=16),
                width=target_bubble_width,
                shadow=ft.BoxShadow(
                    blur_radius=10,
                    spread_radius=0,
                    color="#100F172A",
                    offset=ft.Offset(0, 3),
                ),
            )
            transcript.controls.insert(
                max(0, len(transcript.controls) - 1),
                ft.Row(
                    [bubble],
                    alignment=ft.MainAxisAlignment.END if is_student else ft.MainAxisAlignment.START,
                ),
            )
            return resolved_message_id


        def estimated_composer_lines() -> int:
            value = composer.value or ""
            vw = float(getattr(page, "width", 0) or 1200)
            available_width = max(280.0, vw - 120.0) if vw < 700.0 else max(320.0, vw - 290.0)
            chars_per_line = max(24 if vw < 700.0 else 32, int(available_width / 8.0))
            visual_lines = 0
            for segment in value.split("\n"):
                visual_lines += max(1, (len(segment) + chars_per_line - 1) // chars_per_line)
            return max(1, min(4, visual_lines))

        def update_compact_tutor_layout(*, page_height: float | None = None) -> None:
            line_count = estimated_composer_lines()
            attachment_extra = 34.0 if selected_attachments else 0.0
            composer_height = 52.0 + ((line_count - 1) * 18.0) + attachment_extra
            composer_shell.height = composer_height


        def handle_composer_change(_: object = None) -> None:
            update_compact_tutor_layout()
            page.update()

        def handle_tutor_resize(event: object) -> None:
            new_height = float(
                getattr(event, "height", 0)
                or getattr(page, "height", 0)
                or 760
            )
            new_width = float(
                getattr(event, "width", 0)
                or getattr(page, "width", 0)
                or 1180
            )
            is_mobile_res = new_width < 700.0
            try:
                status_column.visible = not is_mobile_res
            except Exception:
                pass
            shared_w = max(300.0, new_width - 24.0) if is_mobile_res else max(340.0, min(1320.0, new_width - 48.0))
            mode_dropdown.width = 136 if is_mobile_res else 140
            title_text.size = 20 if is_mobile_res else 24
            context_text.size = 11 if is_mobile_res else 13
            if lesson_context_text is not None:
                lesson_context_text.size = 11 if is_mobile_res else 13
            conversation_area.width = shared_w
            composer_container.width = shared_w
            update_compact_tutor_layout()
            try:
                topbar.update()
                conversation_area.update()
                composer_container.update()
                composer_shell.update()
            except Exception:
                pass

        def refresh_attachment_preview() -> None:
            attachment_preview.controls.clear()
            attachment_preview.visible = bool(selected_attachments)
            for item in selected_attachments:
                def remove(_: object = None, attachment_id: str = item.attachment_id) -> None:
                    nonlocal selected_attachments
                    attachment_store.delete(attachment_id, student_id=context.student_id)
                    selected_attachments = [entry for entry in selected_attachments if entry.attachment_id != attachment_id]
                    refresh_attachment_preview()
                    page.update()

                attachment_preview.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.IMAGE_OUTLINED if item.is_image else ft.Icons.DESCRIPTION_OUTLINED, size=16),
                                ft.Text(item.original_name, size=10, max_lines=1),
                                ft.IconButton(ft.Icons.CLOSE, icon_size=15, padding=2, tooltip="Remove", on_click=remove),
                            ],
                            spacing=3,
                            tight=True,
                        ),
                        padding=ft.Padding(left=8, top=1, right=2, bottom=1),
                        bgcolor="#EEF1F8",
                        border_radius=12,
                    )
                )
            update_compact_tutor_layout()

        async def pick_files(_: object = None) -> None:
            nonlocal selected_attachments
            try:
                files = await ft.FilePicker().pick_files(
                    dialog_title="Select test answer file (.txt or .md)",
                    allow_multiple=False,
                    with_data=True,
                )
                if not files:
                    status_text.value = "Attachment selection cancelled"
                    try:
                        page.update()
                    except Exception:
                        pass
                    return

                for picked in files:
                    ext = Path(picked.name).suffix.lower()
                    if ext not in [".txt", ".md"]:
                        add_message(
                            "tutor",
                            "Only .txt and .md files are supported for test answer evaluation right now.",
                            error=True,
                        )
                        status_text.value = "Unsupported file type"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    data = picked.bytes
                    if data is None and getattr(picked, "path", None):
                        try:
                            data = Path(picked.path).read_bytes()
                        except Exception as read_err:
                            add_message(
                                "tutor",
                                f"Unable to read file {picked.name}: {read_err}",
                                error=True,
                            )
                            status_text.value = "File read error"
                            try:
                                page.update()
                            except Exception:
                                pass
                            return

                    if data is None:
                        add_message(
                            "tutor",
                            f"Unable to read file {picked.name}.",
                            error=True,
                        )
                        status_text.value = "File read error"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    if len(data) > 1_048_576:
                        add_message(
                            "tutor",
                            "File size exceeds 1 MB limit (max 1 MB).",
                            error=True,
                        )
                        status_text.value = "File size limit exceeded"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    try:
                        text_content = data.decode("utf-8")
                    except Exception as decode_err:
                        add_message(
                            "tutor",
                            f"Unable to read file text {picked.name}: {decode_err}",
                            error=True,
                        )
                        status_text.value = "File text decode error"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    if not text_content.strip():
                        add_message(
                            "tutor",
                            f"File {picked.name} is empty.",
                            error=True,
                        )
                        status_text.value = "Empty answer file"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    if getattr(ai_service, "_last_generated_test_paper", None) is None:
                        guard_msg = (
                            "No active test paper found. Please generate a test paper first (e.g. type 'generate chapter test')."
                        )
                        add_message("tutor", guard_msg, error=True)
                        status_text.value = "No active test paper"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    add_message("student", f"[Attached answer file: {picked.name}]\n\n{text_content}")
                    set_busy(True, "Evaluating attached test answers...")
                    try:
                        eval_raw = evaluate_test_paper(ai_service._last_generated_test_paper, text_content)
                        eval_formatted = format_tutor_response(eval_raw, student_message=text_content)
                        add_message("tutor", eval_formatted)
                        status_text.value = "Test evaluation complete"
                    finally:
                        set_busy(False, "Ready")
            except Exception as exc:
                add_message("tutor", "Unable to process attached answer file. Please try again or re-attach a valid .txt/.md file.", error=True)
                status_text.value = "Attachment processing error"
                try:
                    page.update()
                except Exception:
                    pass

        def set_busy(value: bool, message: str) -> None:
            busy.visible = value
            send_button.disabled = value
            mic_button.disabled = value
            speak_button.disabled = value or not bool(latest_tutor_answer)
            status_text.value = message
            page.update()

        def resolve_relative_topic_navigation(
            message_text: str,
        ) -> StudentLearningContext | None:
            norm = re.sub(
                r"[^a-z0-9]+",
                " ",
                str(message_text or "").casefold(),
            ).strip()

            if not norm:
                return None

            is_next_topic = bool(
                re.search(
                    r"\b(next\s+topic|topic\s+next|aage\s+topic|agla\s+topic|agle\s+topic)\b",
                    norm,
                )
            )
            is_previous_topic = bool(
                re.search(
                    r"\b(previous\s+topic|prev\s+topic|last\s+topic|pichla\s+topic|pichle\s+topic)\b",
                    norm,
                )
            )

            if not (is_next_topic or is_previous_topic):
                return None

            syllabus = syllabus_repo.find(
                board=context.board,
                medium=context.medium,
                standard=context.standard,
                subject=context.current_subject,
            )

            if syllabus is None:
                return None

            selected_chapter = next(
                (
                    chapter
                    for chapter in syllabus.chapters
                    if chapter.title == context.current_chapter
                ),
                None,
            )

            if selected_chapter is None or not selected_chapter.topics:
                return None

            def nav_norm(value: object) -> str:
                return re.sub(
                    r"[^a-z0-9]+",
                    " ",
                    str(value or "").casefold(),
                ).strip()

            current_topic_norm = nav_norm(context.current_topic)
            current_topic_index = 0

            for topic_index, topic in enumerate(selected_chapter.topics):
                topic_terms = [topic.title, *topic.aliases]
                if any(nav_norm(term) == current_topic_norm for term in topic_terms if term):
                    current_topic_index = topic_index
                    break

            delta = 1 if is_next_topic else -1
            target_topic_index = max(
                0,
                min(len(selected_chapter.topics) - 1, current_topic_index + delta),
            )

            if target_topic_index == current_topic_index:
                return None

            return replace(
                context,
                current_topic=selected_chapter.topics[target_topic_index].title,
            )


        is_sending = False

        def queue_send(_: object = None) -> None:
            nonlocal is_sending
            if is_sending:
                return
            captured_text = (composer.value or "").strip()
            if not captured_text and not selected_attachments:
                notify("Type a question or attach homework first.", error=True)
                return
            is_sending = True
            send_button.disabled = True
            composer.value = ""
            update_compact_tutor_layout()
            try:
                page.update()
            except Exception:
                pass
            page.run_task(send, captured_text)

        async def send(captured_text: str = "", *, is_retry: bool = False) -> None:
            nonlocal is_sending, selected_attachments, latest_tutor_answer
            text = (captured_text or "").strip()
            request_attachments = tuple(selected_attachments)
            started_at = time.perf_counter()
            ai_service.stop_playback()
            tutor_text_control: ft.Text | None = None
            bubble_container: ft.Column | None = None
            tutor_reply_visible = False
            try:
                requested_mode = mode_dropdown.value or LearningMode.EXPLAIN.value
                if requested_mode != context.learning_mode:
                    update_context(replace(context, learning_mode=requested_mode))
                tutor_service_message = text
                tutor_service_context = context

                navigated_context = resolve_relative_topic_navigation(text)
                if navigated_context is not None:
                    update_context(navigated_context)
                    tutor_service_context = navigated_context
                    tutor_service_message = (
                        f"Teach the selected topic: {navigated_context.current_topic}"
                        if navigated_context.current_topic
                        else "Teach the selected topic"
                    )
                else:
                    detected_context, detected = detect_context_from_message(
                        text,
                        context,
                        syllabus_repository=syllabus_repo,
                    )
                    if detected:
                        update_context(detected_context)
                        tutor_service_context = detected_context
                if not is_retry:
                    add_message("student", text or "Please review my attached homework.")

                if ai_service.configured:
                    set_busy(True, "Thinking...")
                else:
                    set_busy(True, "Using local tutor...")

                tutor_text_control = ft.Text("", selectable=True, color=COLOR_TEXT, size=17)
                message_controls: list[ft.Control] = [
                    ft.Text("GyanVerse Tutor", size=12, weight=ft.FontWeight.BOLD, color=COLOR_SUCCESS),
                    tutor_text_control,
                ]
                bubble_container = ft.Column(message_controls, spacing=6)
                viewport_w = float(getattr(page, "width", 0) or 1180)
                shared_w = max(340.0, min(1200.0, viewport_w - 32.0))
                tutor_bubble_width = max(320.0, min(1040.0, shared_w - 40.0))
                tutor_bubble = ft.Container(
                    content=bubble_container,
                    bgcolor=COLOR_TUTOR,
                    border=ft.Border.all(1, COLOR_TUTOR_BORDER),
                    border_radius=ft.BorderRadius.only(
                        top_left=16,
                        top_right=16,
                        bottom_left=4,
                        bottom_right=16,
                    ),
                    padding=ft.Padding(left=18, top=16, right=18, bottom=16),
                    width=tutor_bubble_width,
                    shadow=ft.BoxShadow(
                        blur_radius=10,
                        spread_radius=0,
                        color="#100F172A",
                        offset=ft.Offset(0, 3),
                    ),
                )
                transcript.controls.insert(
                    max(0, len(transcript.controls) - 1),
                    ft.Row([tutor_bubble], alignment=ft.MainAxisAlignment.START),
                )
                page.update()

                last_ui_update_time = [0.0]

                def on_chunk(accumulated_text: str, chunk_text: str) -> None:
                    tutor_text_control.value = accumulated_text
                    t_now = time.perf_counter()
                    if t_now - last_ui_update_time[0] >= 0.08:
                        last_ui_update_time[0] = t_now
                        try:
                            tutor_text_control.update()
                        except Exception:
                            pass

                try:
                    status_text.value = "Answering…"
                    page.update()
                    answer = await asyncio.wait_for(
                        asyncio.to_thread(
                            ai_service.ask_stream,
                            message=tutor_service_message,
                            context=tutor_service_context,
                            attachments=request_attachments,
                            on_chunk=on_chunk,
                        ),
                        timeout=FAST_REPLY_DEADLINE_SECONDS,
                    )
                except asyncio.TimeoutError:
                    ai_service.defer_online_after_failure(
                        f"Tutor response exceeded {FAST_REPLY_DEADLINE_SECONDS:.0f} seconds."
                    )
                    answer = ai_service.offline_answer(
                        message=tutor_service_message,
                        context=tutor_service_context,
                        attachments=request_attachments,
                        reason=ai_service.last_error,
                    )
                latest_tutor_answer = answer
                tutor_text_control.value = answer
                tutor_reply_visible = True

                saved_tutor_message = persist_message(
                    "tutor",
                    answer,
                    backend=ai_service.status_label,
                )
                msg_id = saved_tutor_message.message_id
                if "could not respond right now" in answer.lower():
                    def retry_question(_: object = None, orig_msg: str = text) -> None:
                        composer.value = orig_msg
                        page.update()
                        asyncio.create_task(send(is_retry=True))

                    btn_retry = ft.TextButton("Retry question", icon=ft.Icons.REFRESH, on_click=retry_question)
                    voice_controls_row = ft.Row([btn_retry], alignment=ft.MainAxisAlignment.END)
                else:
                    voice_controls_row, _ = create_tutor_voice_controls(answer, msg_id)

                if len(bubble_container.controls) == 2:
                    bubble_container.controls.append(voice_controls_row)

                speak_button.disabled = False
                selected_attachments = []
                refresh_attachment_preview()

                active_paper = getattr(ai_service, "_last_generated_test_paper", None)
                save_active_test_paper(active_paper)
                m = ai_service.last_metrics
                elapsed = time.perf_counter() - started_at
                paper_suffix = f" • Active test paper ({active_paper.subject})" if active_paper is not None else ""
                if m.stream_used and m.ui_first_visible_ms > 0:
                    first_sec = m.ui_first_visible_ms / 1000.0
                    status_text.value = f"Ready • first text {first_sec:.1f}s • complete {elapsed:.1f}s • {ai_service.status_label}{paper_suffix}"
                else:
                    status_text.value = f"Ready • {elapsed:.1f}s • {ai_service.status_label}{paper_suffix}"

                busy.visible = False
                send_button.disabled = False
                page.update()
                if GYANVERSE_V1_CLOUD_SYNC_ENABLED and firebase_sessions.session is not None:
                    asyncio.create_task(sync_cloud_now(show_result=False, refresh_tutor=False))

                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            engine.record_learning_interaction,
                            student_id=context.student_id,
                            user_text=text or "[homework attachment]",
                            tutor_text=answer,
                        ),
                        timeout=2.0,
                    )
                except Exception:
                    # Learning analytics must never block the visible tutor reply.
                    pass
            except Exception as exc:
                if tutor_reply_visible:
                    status_text.value = "Syllabus answer shown"
                    return
                fallback = ai_service.offline_answer(
                    message=text,
                    context=context,
                    attachments=request_attachments,
                    reason=f"{type(exc).__name__}: {exc}",
                )
                latest_tutor_answer = fallback
                if tutor_text_control is not None:
                    tutor_text_control.value = fallback
                    tutor_reply_visible = True
                else:
                    add_message("tutor", fallback)
                status_text.value = "Syllabus answer shown"
            finally:
                busy.visible = False
                send_button.disabled = False
                mic_button.disabled = False
                is_sending = False
                page.update()


        def handle_voice_state(event: object) -> None:
            state = getattr(event, "state", None)
            state_label = getattr(state, "value", None) or str(state or "updated")
            status_text.value = f"Voice recorder: {state_label}"
            page.update()

        recorder = None
        if far is not None:
            recorder = far.AudioRecorder(on_state_change=handle_voice_state)
            page.services.append(recorder)

        async def _read_recorded_wav(path: Path) -> bytes:
            for _ in range(30):
                if path.exists() and path.stat().st_size > 44:
                    data = await asyncio.to_thread(path.read_bytes)
                    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
                        return data
                await asyncio.sleep(0.1)
            raise AIServiceError("The microphone did not produce a valid WAV recording. Check Windows microphone access and try again.")

        async def toggle_recording(_: object = None) -> None:
            nonlocal voice_state, voice_capture_path
            if recorder is None:
                notify("Voice recorder extension is unavailable. Continue by typing.", error=True)
                return
            try:
                if voice_state == VoiceState.RECORDING:
                    voice_state = VoiceState.PROCESSING
                    mic_button.icon = ft.Icons.MIC_NONE_ROUNDED
                    returned_path = await recorder.stop_recording()
                    capture_path = Path(returned_path) if returned_path else voice_capture_path
                    if capture_path is None:
                        raise AIServiceError("The recorder did not return an audio file.")
                    wav_bytes = await _read_recorded_wav(capture_path)
                    set_busy(True, f"Converting voice with {ai_service.transcription_backend}...")
                    transcript_text = await asyncio.to_thread(
                        ai_service.transcribe,
                        wav_bytes,
                        language_hint=context.preferred_language,
                    )
                    composer.value = transcript_text
                    update_compact_tutor_layout()
                    await composer.focus()
                    voice_state = VoiceState.READY
                    status_text.value = "Voice text ready — edit it before sending"
                    try:
                        capture_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    voice_capture_path = None
                else:
                    if not ai_service.transcription_available:
                        raise AIServiceError("Voice transcription is not configured. Typing remains available.")
                    voice_state = VoiceState.REQUESTING_PERMISSION
                    status_text.value = "Requesting microphone permission..."
                    page.update()
                    if not await recorder.has_permission():
                        voice_state = VoiceState.UNAVAILABLE
                        raise AIServiceError(
                            "Microphone permission was denied. Enable it in Windows Settings > Privacy & security > Microphone."
                        )
                    if not await recorder.is_supported_encoder(far.AudioEncoder.WAV):
                        raise AIServiceError("WAV microphone recording is not supported on this device.")
                    voice_capture_path = Path(tempfile.gettempdir()) / f"gyanverse_voice_{uuid.uuid4().hex}.wav"
                    voice_capture_path.unlink(missing_ok=True)
                    started = await recorder.start_recording(
                        output_path=str(voice_capture_path),
                        configuration=far.AudioRecorderConfiguration(
                            encoder=far.AudioEncoder.WAV,
                            sample_rate=16_000,
                            channels=1,
                            suppress_noise=True,
                            cancel_echo=True,
                            auto_gain=True,
                        ),
                    )
                    if not started:
                        raise AIServiceError("The microphone could not start. Close other apps using the mic and try again.")
                    voice_state = VoiceState.RECORDING
                    mic_button.icon = ft.Icons.STOP_CIRCLE_OUTLINED
                    status_text.value = "Recording — speak now, then tap the red stop button"
            except Exception as exc:
                voice_state = VoiceState.ERROR
                mic_button.icon = ft.Icons.MIC_NONE_ROUNDED
                notify(str(exc), error=True)
            finally:
                busy.visible = False
                send_button.disabled = False
                mic_button.disabled = False
                page.update()

        def handle_audio_state(event: object) -> None:
            nonlocal voice_state
            state_name = str(getattr(event, "state", "")).lower()
            if "playing" in state_name:
                voice_state = VoiceState.PLAYING
                status_text.value = "Playing tutor answer"
            elif "completed" in state_name or "stopped" in state_name:
                voice_state = VoiceState.IDLE
                status_text.value = "Ready"
            page.update()

        async def speak_last(_: object = None) -> None:
            nonlocal voice_state, active_audio
            if not latest_tutor_answer:
                notify("No tutor answer is available to read aloud.", error=True)
                return
            if fta is None and not ai_service.native_playback_available:
                notify("Audio playback is unavailable. The text answer remains readable.", error=True)
                return
            try:
                voice_state = VoiceState.PROCESSING
                set_busy(True, "Preparing spoken answer...")
                audio_bytes = await asyncio.wait_for(
                    asyncio.to_thread(
                        ai_service.synthesize,
                        latest_tutor_answer,
                        language_hint=context.preferred_language,
                    ),
                    timeout=SPOKEN_ANSWER_DEADLINE_SECONDS,
                )
                if not audio_bytes.startswith(b"RIFF") or b"WAVE" not in audio_bytes[:16]:
                    raise AIServiceError("Spoken answer did not return a valid WAV audio file.")

                if ai_service.native_playback_available:
                    voice_state = VoiceState.PLAYING
                    status_text.value = (
                        f"Playing tutor answer • {ai_service.last_tts_backend or ai_service.tts_backend_label}"
                    )
                    page.update()
                    await asyncio.wait_for(
                        asyncio.to_thread(ai_service.play_wav_bytes, audio_bytes),
                        timeout=SPOKEN_PLAYBACK_DEADLINE_SECONDS,
                    )
                    voice_state = VoiceState.IDLE
                    status_text.value = "Ready"
                    return

                if active_audio is not None:
                    try:
                        await active_audio.release()
                    except Exception:
                        pass
                    try:
                        page.services.remove(active_audio)
                    except ValueError:
                        pass

                audio = fta.Audio(
                    src=base64.b64encode(audio_bytes).decode("utf-8"),
                    autoplay=False,
                    volume=1.0,
                    release_mode=fta.ReleaseMode.STOP,
                    on_state_change=handle_audio_state,
                )
                page.services.append(audio)
                active_audio = audio

                # Non-Windows runtimes retain the Flet audio-service fallback.
                page.update()
                await asyncio.sleep(0.15)
                await asyncio.wait_for(audio.play(), timeout=20.0)

                voice_state = VoiceState.PLAYING
                status_text.value = "Playing tutor answer"
            except asyncio.TimeoutError:
                voice_state = VoiceState.ERROR
                notify(
                    "Spoken answer timed out. The text answer remains available; tap the speaker to retry.",
                    error=True,
                )
            except Exception as exc:
                voice_state = VoiceState.ERROR
                notify(str(exc), error=True)
            finally:
                busy.visible = False
                send_button.disabled = False
                mic_button.disabled = False
                speak_button.disabled = not bool(latest_tutor_answer)
                page.update()

        def mode_changed(_: object = None) -> None:
            try:
                update_context(replace(context, learning_mode=mode_dropdown.value or LearningMode.EXPLAIN.value))
                status_text.value = f"Mode: {mode_label(context.learning_mode)}"
                page.update()
            except Phase11Error as exc:
                notify(str(exc), error=True)

        mode_dropdown.on_change = mode_changed
        attach_button.on_click = pick_files
        send_button.on_click = queue_send
        composer.on_change = handle_composer_change
        composer.on_submit = queue_send
        mic_button.on_click = toggle_recording
        speak_button.on_click = speak_last

        stored_messages = conversation_store.list_messages(
            conversation_id=active_conversation.conversation_id,
            owner_id=current_owner_id,
            limit=500,
        )
        restored_active_test_paper = restore_active_test_paper()
        restored_turns: list[tuple[str, str]] = []
        pending_student_text = ""
        for stored_message in stored_messages:
            add_message(
                stored_message.role,
                stored_message.text,
                persist=False,
                message_id=stored_message.message_id,
                backend=stored_message.backend,
            )
            if stored_message.role == "student":
                pending_student_text = stored_message.text
            elif stored_message.role == "tutor":
                latest_tutor_answer = stored_message.text
                if pending_student_text:
                    restored_turns.append((pending_student_text, stored_message.text))
                    pending_student_text = ""
        ai_service.restore_session_history(restored_turns)

        if stored_messages:
            active_test_suffix = " • Active test paper restored" if restored_active_test_paper else ""
            status_text.value = f"Restored {len(stored_messages)} local chat message(s){active_test_suffix}"
        else:
            is_mobile_welcome = viewport_width < 700.0
            welcome_text = (
                f"Namaste {context.name}! Profile: {context.board} • Std {context.standard}.\n"
                "Ask a doubt or paste a homework question below."
                if is_mobile_welcome
                else (
                    f"Namaste {context.name}. Your current learning profile is {context.board} • {context.medium} • Standard {context.standard}. "
                    "Tell me what your class studied today, ask a doubt, or attach homework with +."
                )
            )
            add_message(
                "tutor",
                welcome_text,
                persist=False,
            )

        composer_shell = ft.Container(
            height=52,
            content=ft.Column(
                [
                    attachment_preview,
                    ft.Row(
                        [
                            attach_button,
                            composer_slot,
                            busy,
                            send_button,
                        ],
                        spacing=2,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            padding=ft.Padding(left=6, top=2, right=4, bottom=2),
            bgcolor=COLOR_SURFACE,
            border=ft.Border.all(1, COLOR_SOFT_BORDER),
            border_radius=18,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            shadow=ft.BoxShadow(
                blur_radius=18,
                spread_radius=0,
                color="#220F172A",
                offset=ft.Offset(0, 6),
            ),
        )

        lesson_context_text = ft.Text(
            context.context_label,
            size=11 if is_mobile else 13,
            color=COLOR_MUTED,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        context_banner_content = (
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.AUTO_AWESOME, color=COLOR_ACCENT, size=16),
                            ft.Container(content=lesson_context_text, expand=True),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            mode_dropdown,
                            ft.Container(expand=True),
                            ft.IconButton(
                                ft.Icons.EDIT_OUTLINED,
                                tooltip="Change student profile",
                                icon_size=16,
                                on_click=open_profile_dialog,
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=2,
                tight=True,
            )
            if is_mobile
            else ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_AWESOME, color=COLOR_ACCENT, size=18),
                    ft.Container(
                        content=lesson_context_text,
                        expand=True,
                    ),
                    mode_dropdown,
                    ft.IconButton(
                        ft.Icons.EDIT_OUTLINED,
                        tooltip="Change student profile",
                        icon_size=18,
                        on_click=open_profile_dialog,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        context_banner = ft.Container(
            content=context_banner_content,
            padding=ft.Padding(left=8 if is_mobile else 12, top=4 if is_mobile else 6, right=4 if is_mobile else 6, bottom=4 if is_mobile else 6),
            bgcolor=COLOR_BANNER,
            border=ft.Border.all(1, COLOR_BANNER_BORDER),
            border_radius=12,
            shadow=ft.BoxShadow(
                blur_radius=8,
                spread_radius=0,
                color="#0F059669",
                offset=ft.Offset(0, 2),
            ),
        )

        conversation_area = ft.Container(
            width=shared_conversation_width,
            expand=True,
            content=ft.Column(
                [context_banner, transcript_surface],
                expand=True,
                spacing=6 if is_mobile else 8,
            ),
        )
        composer_container = ft.Container(
            width=shared_conversation_width,
            content=composer_shell,
        )

        page.on_resize = handle_tutor_resize
        refresh_attachment_preview()

        return ft.Container(
            expand=True,
            content=ft.Container(
                expand=True,
                padding=ft.Padding(left=6 if is_mobile else 16, top=6 if is_mobile else 10, right=6 if is_mobile else 16, bottom=6 if is_mobile else 8),
                alignment=ft.alignment.Alignment(0, -1),
                content=ft.Column(
                    [conversation_area, composer_container],
                    expand=True,
                    spacing=6 if is_mobile else 8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.START,
                ),
            ),
        )

    builders = {
        "home": build_home,
        "tutor": build_tutor,
        "sync": build_sync,
        "homework": build_homework,
        "revision": lambda: build_reports("revision"),
        "progress": lambda: build_reports("progress"),
        "syllabus": build_syllabus,
        "settings": build_settings,
    }

    def show_view(key: str) -> None:
        nonlocal current_view
        current_view = key if key in builders else "tutor"
        label = next((item[1] for item in NAV_ITEMS if item[0] == current_view), "Tutor")
        title_text.value = label
        page.on_resize = None
        body.content = builders[current_view]()
        page.update()

    async def open_drawer(_: object = None) -> None:
        await page.show_drawer()

    async def drawer_changed(event: object) -> None:
        index = int(getattr(event.control, "selected_index", 1))
        key = NAV_ITEMS[index][0]
        show_view(key)
        await page.close_drawer()

    menu_button.on_click = open_drawer
    new_chat_button.on_click = start_new_chat
    account_button.on_click = lambda _: show_view("settings")
    page.on_login = google_login_completed
    page.on_logout = google_logout_completed
    refresh_cloud_status()
    page.drawer = ft.NavigationDrawer(
        selected_index=1,
        width=292,
        bgcolor=COLOR_SURFACE,
        indicator_color="#E2E9FF",
        on_change=drawer_changed,
        controls=[
            ft.Container(
                content=ft.Row(
                    [
                        ft.Image(src="logo_mark.png", width=42, height=42, error_content=ft.Icon(ft.Icons.SCHOOL, color=COLOR_PRIMARY)),
                        ft.Column(
                            [
                                ft.Text("GyanVerse Academy", size=17, weight=ft.FontWeight.BOLD, color=COLOR_TEXT),
                                ft.Text("Your personal tutor", size=10, color=COLOR_MUTED),
                            ],
                            spacing=0,
                        ),
                    ]
                ),
                padding=ft.Padding(left=20, top=20, right=12, bottom=14),
            ),
            ft.Divider(height=1),
            *[
                ft.NavigationDrawerDestination(icon=icon, selected_icon=selected_icon, label=label)
                for _, label, icon, selected_icon in NAV_ITEMS
            ],
        ],
    )

    status_column = ft.Column(
        [status_text, cloud_status_text],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.END,
        visible=not (float(getattr(page, "width", 0) or 1180) < 700.0),
    )
    context_text.max_lines = 1
    context_text.overflow = ft.TextOverflow.ELLIPSIS
    title_text.max_lines = 1
    title_text.overflow = ft.TextOverflow.ELLIPSIS

    topbar = ft.Container(
        content=ft.Row(
            [
                menu_button,
                ft.Column([title_text, context_text], spacing=0, expand=True),
                status_column,
                new_chat_button,
                account_button,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(
            left=4 if initial_is_mobile else 6,
            top=4 if initial_is_mobile else 6,
            right=6 if initial_is_mobile else 10,
            bottom=4 if initial_is_mobile else 6,
        ),
        bgcolor=COLOR_SURFACE,
        border=ft.Border(bottom=ft.BorderSide(1, COLOR_SOFT_BORDER)),
        shadow=ft.BoxShadow(
            blur_radius=10,
            spread_radius=0,
            color="#100F172A",
            offset=ft.Offset(0, 2),
        ),
    )

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column([topbar, body], expand=True, spacing=0),
        )
    )
    show_view("tutor")
    saved_oauth_token = oauth_token_store.load() if google_provider is not None else ""
    if saved_oauth_token:
        refresh_cloud_status("Cloud: restoring Google session…")
        page.update()
        page.run_task(page.login, google_provider, saved_token=saved_oauth_token)
    if not context.onboarding_complete:
        open_profile_dialog(first_use=True)


if __name__ == "__main__":
    oauth_port = int(os.getenv("GYANVERSE_OAUTH_PORT", "8550"))
    ft.run(main, assets_dir="assets", port=oauth_port)
