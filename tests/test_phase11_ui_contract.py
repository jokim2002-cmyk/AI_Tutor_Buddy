import ast
import struct
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "gyanverse_ui.py").read_text(encoding="utf-8")
CORE = (ROOT / "phase11_core.py").read_text(encoding="utf-8")


class Phase11UIContractTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for name in ("main.py", "gyanverse_ui.py", "phase11_core.py", "phase11_ai.py", "scripts/launch_gyanverse_hidden.pyw"):
            ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)

    def test_hidden_drawer_replaces_permanent_rail(self):
        self.assertIn("ft.NavigationDrawer(", UI)
        self.assertIn("page.show_drawer()", UI)
        self.assertIn("page.close_drawer()", UI)
        self.assertNotIn("NavigationRail(", UI)

    def test_new_chat_starts_fresh_conversation_without_deleting_history(self):
        self.assertIn("new_chat_button = ft.IconButton(", UI)
        self.assertIn('tooltip="Start new chat"', UI)
        self.assertIn("def start_new_chat", UI)
        self.assertIn("conversation_store.create_conversation(", UI)
        self.assertIn('title="New conversation"', UI)
        self.assertIn("new_chat_button.on_click = start_new_chat", UI)
        new_chat_block = UI.split("def start_new_chat", 1)[1].split("def refresh_cloud_status", 1)[0]
        self.assertIn('show_view("tutor")', new_chat_block)
        self.assertNotIn("delete", new_chat_block.casefold())
        self.assertNotIn("list_messages", new_chat_block)

    def test_tutor_composer_chat_only_v1_contracts_exist(self):
        # Assert Chat UI elements exist
        for marker in (
            "multiline=True",
            "ft.FilePicker().pick_files",
            "with_data=True",
            "LearningMode.HOMEWORK",
            "attach_button",
            "send_button",
            "composer_slot",
        ):
            self.assertIn(marker, UI)

        # Assert voice controls are NOT present in composer row
        composer_row_block = UI.split("composer_shell = ft.Container", 1)[1].split("lesson_context_text =", 1)[0]
        self.assertNotIn("speak_button", composer_row_block)
        self.assertNotIn("mic_button", composer_row_block)
        self.assertIn("attach_button", composer_row_block)
        self.assertIn("send_button", composer_row_block)

        # Assert welcome text does not mention speak using the mic
        welcome_block = UI.split('add_message(\n                "tutor",', 1)[1].split('composer_shell =', 1)[0]
        self.assertNotIn("speak using the mic", welcome_block.casefold())

        # Assert create_tutor_voice_controls appends ONLY btn_copy and no play/stop/replay buttons or voice status text
        voice_controls_block = UI.split("def create_tutor_voice_controls", 1)[1].split("def persist_message", 1)[0]
        self.assertIn("btn_copy", voice_controls_block)
        self.assertNotIn("btn_play", voice_controls_block)
        self.assertNotIn("btn_stop", voice_controls_block)
        self.assertNotIn("btn_replay", voice_controls_block)
        self.assertNotIn("Natural voice available", voice_controls_block)

    def test_no_runtime_or_user_facing_string_contains_tap_replay(self):
        AI = (ROOT / "phase11_ai.py").read_text(encoding="utf-8")
        self.assertNotIn("Tap Replay", UI)
        self.assertNotIn("Tap Replay", CORE)
        self.assertNotIn("Tap Replay", AI)

    def test_no_duplicate_online_error_card_on_scope_mismatch(self):
        from phase11_ai import GyanVerseAIService
        from phase11_core import StudentLearningContext
        service = GyanVerseAIService(api_key="mock_key")
        ctx = StudentLearningContext(
            board="GSEB",
            medium="English",
            standard=8,
            current_subject="Science & Technology",
            current_chapter="Chapter 2 - Microorganisms : Friend and Foe",
        ).validate()
        resp = service.ask_stream(
            message="explain fraction comparison and rational numbers",
            context=ctx,
        )
        self.assertEqual(service.last_backend, "local scope guard")
        self.assertEqual(service.last_error, "")
        self.assertNotIn("could not respond right now", resp.lower())
        self.assertNotIn("Tap Retry", resp)
        self.assertIn("select Mathematics", resp)


    def test_tutor_transcript_uses_fixed_height_non_lazy_column(self):
        self.assertIn("viewport_height = float(getattr(page, \"height\", 0) or 760)", UI)
        self.assertIn("mobile_reserved_height = 335.0", UI)
        self.assertIn("viewport_height - (mobile_reserved_height if is_mobile else 230.0)", UI)
        self.assertIn("transcript_bottom_spacer = ft.Container(height=16 if is_mobile else 24)", UI)
        self.assertIn("transcript = ft.Column(", UI)
        self.assertIn("height=transcript_height", UI)
        self.assertIn("horizontal_alignment=ft.CrossAxisAlignment.STRETCH", UI)
        self.assertIn("scroll=ft.ScrollMode.AUTO", UI)
        self.assertIn("auto_scroll=True", UI)
        self.assertIn("auto_scroll_animation=0", UI)
        self.assertIn("controls=[transcript_bottom_spacer]", UI)
        self.assertIn("transcript_surface = ft.Container(", UI)
        self.assertIn("content=transcript", UI)
        self.assertIn("[context_banner, transcript_surface]", UI)
        self.assertIn("page.on_resize = handle_tutor_resize", UI)
        self.assertIn("transcript_surface.height = resized_height", UI)
        self.assertIn("transcript_surface.update()", UI)
        self.assertIn("transcript.controls.insert(", UI)
        self.assertNotIn("transcript = ft.ListView(", UI)
        self.assertNotIn("build_controls_on_demand", UI)
        self.assertNotIn("cache_extent", UI)
        self.assertNotIn("await transcript.scroll_to(", UI)
        transcript_block = UI.split("transcript = ft.Column(", 1)[1].split("composer = ft.TextField(", 1)[0]
        self.assertNotIn("expand=True", transcript_block)


    def test_tutor_layout_uses_auto_growing_ultra_compact_composer(self):
        composer_block = UI.split("composer = ft.TextField(", 1)[1].split("mode_dropdown = ft.Dropdown(", 1)[0]
        self.assertIn("multiline=True", composer_block)
        self.assertIn("min_lines=1", composer_block)
        self.assertIn("max_lines=4", composer_block)
        self.assertIn("shift_enter=True", composer_block)
        self.assertIn("dense=True", composer_block)
        self.assertIn("content_padding=ft.Padding(left=0, top=4, right=0, bottom=4)", composer_block)
        self.assertIn("text_size=15 if is_mobile else 16", composer_block)
        self.assertIn("composer_slot = ft.Container(content=composer, expand=True)", composer_block)
        self.assertIn("composer.on_change = handle_composer_change", UI)
        self.assertIn("composer.on_submit = queue_send", UI)
        self.assertIn("def estimated_composer_lines() -> int:", UI)
        self.assertIn("composer_height = 52.0 + ((line_count - 1) * 18.0) + attachment_extra", UI)
        self.assertIn("attachment_extra = 34.0 if selected_attachments else 0.0", UI)
        self.assertIn("header_offset = 335.0 if is_m else 180.0", UI)
        mode_block = UI.split("mode_dropdown = ft.Dropdown(", 1)[1].split("attachment_preview = ft.Row(", 1)[0]
        self.assertIn("width=110 if is_mobile else 140", mode_block)
        self.assertIn("text_size=12 if is_mobile else 13", mode_block)
        shell_block = UI.split("composer_shell = ft.Container(", 1)[1].split("context_banner = ft.Container(", 1)[0]
        self.assertIn("height=52", shell_block)
        self.assertIn("padding=ft.Padding(left=6, top=2, right=4, bottom=2)", shell_block)
        self.assertIn("border_radius=18", shell_block)
        self.assertIn("                            attach_button,", shell_block)
        self.assertIn("                            busy,\n                            send_button,", shell_block)
        self.assertIn("                        spacing=2,", shell_block)
        self.assertIn("attachment_preview.visible = bool(selected_attachments)", UI)
        self.assertNotIn("Enter sends • Shift+Enter adds a new line", shell_block)
        banner_block = UI.split("context_banner = ft.Container(", 1)[1].split("conversation_area = ft.Container(", 1)[0]
        banner_content_block = UI.split("context_banner_content = (", 1)[1].split("context_banner = ft.Container(", 1)[0]
        self.assertIn("context_banner_content = (", UI)
        self.assertIn("                            mode_dropdown,", banner_content_block)
        self.assertIn("                        expand=True,", banner_content_block)
        self.assertIn("content=context_banner_content", banner_block)
        self.assertIn("alignment=ft.MainAxisAlignment.SPACE_BETWEEN", UI)
        self.assertIn("conversation_area = ft.Container(", UI)
        self.assertNotIn("                        transcript,\n                        composer_shell,", UI)

    def test_async_composer_focus_is_awaited(self):
        self.assertIn("await composer.focus()", UI)
        self.assertNotIn("\n                    composer.focus()", UI)
    def test_context_and_syllabus_contracts_exist(self):
        for marker in (
            "LearningContextStore",
            "onboarding_complete",
            "SyllabusRepository",
            "content_origin",
            "official_coverage_percent",
        ):
            self.assertIn(marker, UI + CORE)

    def test_ui_board_and_standard_dropdown_options(self):
        self.assertIn('options=[ft.dropdown.Option(item) for item in ("GSEB", "CBSE")]', UI)
        self.assertIn('options=[ft.dropdown.Option(str(item)) for item in range(1, 11)]', UI)
        self.assertNotIn('options=[ft.dropdown.Option(item) for item in ("GSEB", "CBSE", "ICSE", "Other")]', UI)

    def test_profile_dialog_uses_non_overlapping_dropdown_layout(self):
        self.assertIn('name_field = ft.TextField(label="Student name", value=context.name, width=520)', UI)
        self.assertIn('width=560', UI)
        self.assertIn('height=560', UI)
        self.assertIn('ft.Row([board_field, medium_field, standard_field], spacing=12, wrap=True)', UI)
        self.assertIn('subject_field = ft.Dropdown(label="Subject", width=520)', UI)
        self.assertIn('chapter_field = ft.Dropdown(label="Chapter", width=520)', UI)
        self.assertIn('topic_field = ft.Dropdown(label="Topic", width=520)', UI)
        self.assertIn('tight=False', UI)

    def test_mobile_width_and_assets(self):
        self.assertIn("page.window.min_width = 360", UI)
        self.assertIn("initial_is_mobile = float(getattr(page, \"width\", 0) or 1180) < 700.0", UI)
        self.assertIn("is_mobile = viewport_width < 700.0", UI)
        self.assertIn("status_column = ft.Column(", UI)
        self.assertIn("visible=not (float(getattr(page, \"width\", 0) or 1180) < 700.0)", UI)
        self.assertIn("width=110 if is_mobile else 140", UI)
        expected = {
            "icon.png": (1024, 1024),
            "icon_android.png": (1024, 1024),
            "icon_web.png": (512, 512),
            "icon_windows.png": (512, 512),
            "splash.png": (1080, 1920),
            "logo_mark.png": (512, 512),
        }
        for name, dimensions in expected.items():
            path = ROOT / "assets" / name
            self.assertTrue(path.exists(), name)
            with path.open("rb") as stream:
                self.assertEqual(stream.read(8), b"\x89PNG\r\n\x1a\n")
                length = struct.unpack(">I", stream.read(4))[0]
                self.assertEqual(stream.read(4), b"IHDR")
                width, height = struct.unpack(">II", stream.read(8))
            self.assertGreaterEqual(length, 13)
            self.assertEqual((width, height), dimensions)

    def test_packaging_configuration_preserves_android_gate(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["tool"]["flet"]["android"]["min_sdk_version"], 24)
        permissions = config["tool"]["flet"]["android"]["permission"]
        self.assertNotIn("android.permission.RECORD_AUDIO", permissions)
        self.assertTrue(permissions["android.permission.CAMERA"])
        dependencies = config["project"]["dependencies"]
        self.assertFalse(any(item.startswith("flet-audio-recorder") for item in dependencies))
        self.assertFalse(any(item.startswith("flet-audio") for item in dependencies))
        self.assertFalse(
            any(item.startswith("SpeechRecognition") for item in dependencies),
            "Android Flet builds evaluate markers on the Windows host, so SpeechRecognition must not be a base dependency.",
        )
        optional = config["project"].get("optional-dependencies", {})
        self.assertIn("desktop-voice", optional)
        self.assertTrue(any(item.startswith("SpeechRecognition") for item in optional["desktop-voice"]))
        self.assertFalse(any(item.startswith("sounddevice") for item in dependencies))


    def test_hidden_desktop_launcher_contract(self):
        launcher = (ROOT / "scripts" / "launch_gyanverse_hidden.pyw").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "run_phase11_app.ps1").read_text(encoding="utf-8")
        self.assertIn("data", launcher)
        self.assertIn("logs", launcher)
        self.assertIn("pythonw.exe", runner)
        self.assertIn("-WindowStyle Hidden", runner)
        self.assertNotIn("flet run main.py", runner)


    def test_tutor_reply_has_hard_deadline_and_nonblocking_analytics(self):
        for marker in (
            "FAST_REPLY_DEADLINE_SECONDS = 15.0",
            "asyncio.wait_for(",
            "ai_service.offline_answer(",
            "ai_service.defer_online_after_failure(",
            "ai_service.status_label",
            "Learning analytics must never block the visible tutor reply",
            "Ready • {elapsed:.1f}s",
        ):
            self.assertIn(marker, UI)

    def test_context_updates_skip_redundant_disk_and_database_writes(self):
        self.assertIn("meaningful_fields = (", UI)
        self.assertIn("if all(getattr(context, field) == getattr(validated, field)", UI)
        self.assertIn("if requested_mode != context.learning_mode", UI)

    def test_context_updates_switch_active_conversation_scope(self):
        update_context_block = UI.split("def update_context", 1)[1].split("def notify", 1)[0]
        self.assertIn("lesson_scope_changed = any(", update_context_block)
        self.assertIn('"current_subject"', update_context_block)
        self.assertIn('"current_chapter"', update_context_block)
        self.assertIn("activate_owner(current_owner_id)", update_context_block)
        self.assertIn("ai_service.reset_session()", update_context_block)

    def test_no_obsolete_project_drive_hardcoding_in_runtime_files(self):
        runtime = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("main.py", "gyanverse_ui.py", "phase11_core.py", "phase11_ai.py")
        )
        self.assertNotIn("D:\\Ai_Tutor_Buddy", runtime)
        self.assertNotIn("C:\\Ai_Tutor_Buddy", runtime)
        self.assertNotIn("E:\\Ai_Tutor_Buddy", runtime)

    def test_ui_button_wiring_and_contrast_contracts(self):
        self.assertIn('COLOR_BACKGROUND = "#F8F9FA"', UI)
        self.assertIn('COLOR_TEXT = "#0F172A"', UI)
        self.assertIn('COLOR_MUTED = "#334155"', UI)
        self.assertIn('COLOR_USER = "#E0EBFF"', UI)
        self.assertIn("send_button.on_click = queue_send", UI)
        self.assertIn("attach_button.on_click = pick_files", UI)
        self.assertIn("mic_button.on_click = toggle_recording", UI)
        self.assertIn("speak_button.on_click = speak_last", UI)
        self.assertIn("board_field.on_change = profile_scope_changed", UI)
        self.assertIn("subject_field.on_change = subject_changed", UI)
        self.assertIn("chapter_field.on_change = chapter_changed", UI)
        self.assertIn("save_profile", UI)
        self.assertIn("retry_question", UI)

    def test_profile_dropdown_cascade_logic(self):
        from phase11_core import GSEBSyllabusRepository
        repo = GSEBSyllabusRepository(ROOT / "syllabus")
        syllabi = repo.all(board="GSEB")
        g8_eng = [s for s in syllabi if s.medium.casefold() == "english" and s.standard == 8]
        subjects = sorted({s.subject for s in g8_eng})
        self.assertIn("Mathematics", subjects)
        self.assertIn("Science & Technology", subjects)
        self.assertIn("Social Science", subjects)

        math_syllabus = next(s for s in g8_eng if s.subject == "Mathematics")
        chapters = [c.title for c in math_syllabus.chapters]
        self.assertTrue(len(chapters) >= 1)
        self.assertIn("Chapter 1 - Rational Numbers", chapters[0])

        topics = [t.title for t in math_syllabus.chapters[0].topics]
        self.assertTrue(len(topics) >= 1)

    def test_ui_readability_and_chatgpt_layout_contracts(self):
        self.assertIn('COLOR_TEXT = "#0F172A"', UI)
        self.assertIn("size=20 if initial_is_mobile else 24", UI)
        self.assertIn("size=font_size", UI)
        self.assertNotIn("line_height", UI)
        self.assertIn("text_size=15 if is_mobile else 16", UI)
        self.assertIn("shared_conversation_width = max(300.0, viewport_width - 24.0) if is_mobile else max(340.0, min(1320.0, viewport_width - 48.0))", UI)
        self.assertIn("horizontal_alignment=ft.CrossAxisAlignment.CENTER", UI)
        self.assertIn("alignment=ft.alignment.Alignment(0, -1)", UI)
        self.assertNotIn("top_center", UI)
        self.assertIn("target_bubble_width = max(280.0, shared_w - 12.0) if is_mobile_screen else max(320.0, min(860.0 if is_student else 1040.0, shared_w - 40.0))", UI)
        self.assertIn("ft.Icons.COPY", UI)
        self.assertIn("page.set_clipboard(", UI)
        self.assertIn("transcript_bottom_spacer = ft.Container(height=16 if is_mobile else 24)", UI)
        self.assertIn("scroll=ft.ScrollMode.AUTO", UI)
        self.assertIn("height=560", UI)

    def test_android_mobile_shell_uses_root_safe_area_and_preserves_composer(self):
        self.assertIn("page.add(\n        ft.SafeArea(", UI)
        self.assertIn("content=ft.Column([topbar, body], expand=True, spacing=0)", UI)
        build_tutor_return = UI.split("page.on_resize = handle_tutor_resize", 1)[1].split("builders = {", 1)[0]
        self.assertIn("return ft.Container(", build_tutor_return)
        self.assertNotIn("return ft.SafeArea(", build_tutor_return)
        self.assertIn("header_offset = 335.0 if is_m else 180.0", UI)
        self.assertIn("title_text.size = 20 if is_mobile_res else 24", UI)
        self.assertIn("context_text.size = 11 if is_mobile_res else 13", UI)


    def test_phase2b_attachment_answer_submission_contracts(self):
        self.assertIn("attach_button.on_click = pick_files", UI)
        self.assertIn("Only .txt and .md files are supported for test answer evaluation right now.", UI)
        self.assertIn("File size exceeds 1 MB limit (max 1 MB).", UI)
        self.assertIn("No active test paper found. Please generate a test paper first", UI)
        self.assertIn("eval_raw = evaluate_test_paper(ai_service._last_generated_test_paper, text_content)", UI)

    def test_attachment_evaluation_handler_executes_without_name_errors(self):
        import gyanverse_ui
        from phase11_core import (
            GSEBSyllabusRepository,
            render_test_paper,
            parse_test_paper_scope,
        )

        self.assertTrue(hasattr(gyanverse_ui, "evaluate_test_paper"))
        self.assertTrue(hasattr(gyanverse_ui, "format_tutor_response"))

        repo = GSEBSyllabusRepository(ROOT / "syllabus")
        syl = repo.find(board="GSEB", medium="English", standard=8, subject="Science & Technology")
        self.assertIsNotNone(syl)
        scope = parse_test_paper_scope("Generate Science Chapter 1 25-mark test paper", None, syl)
        _, paper = render_test_paper(syl, scope, context=None)
        ans = (
            "1. Drip irrigation system saves water by delivering water directly to roots.\n"
            "2. Plough and hoe are traditional tools used for preparation of soil.\n"
            "3. Weeds are unwanted plants and weedicides control them."
        )

        eval_raw = gyanverse_ui.evaluate_test_paper(paper, ans)
        eval_formatted = gyanverse_ui.format_tutor_response(eval_raw, student_message=ans)

        self.assertIn("Total Marks:", eval_formatted)
        self.assertIn("Per-Question Evaluation:", eval_formatted)
        self.assertIn("Source type: Teacher-authored content.", eval_formatted)

    def test_generate_test_paper_persists_state_and_enables_attachment_eval(self):
        from phase11_ai import GyanVerseAIService
        from phase11_core import GSEBSyllabusRepository, StudentLearningContext
        import gyanverse_ui

        repo = GSEBSyllabusRepository(ROOT / "syllabus")
        ai = GyanVerseAIService(syllabus_repository=repo, api_key="mock_key")
        ctx = StudentLearningContext(
            student_id="s1",
            name="Student",
            board="GSEB",
            medium="English",
            standard=8,
            current_subject="Science & Technology",
            current_chapter="Chapter 1 - Crop Production and Management",
            onboarding_complete=True,
        )

        self.assertIsNone(ai._last_generated_test_paper)

        prompts = [
            "Chapter 1 ka 25 marks test banao",
            "Generate Science Chapter 1 25-mark test paper",
            "Full book test banao",
        ]

        ans_txt = (
            "1. Paddy is a Kharif crop and wheat is a Rabi crop.\n"
            "2. Damaged seeds should be separated because they are hollow and weak.\n"
            "3. Drip irrigation."
        )

        for p in prompts:
            ai._last_generated_test_paper = None
            _ = ai.ask_stream(message=p, context=ctx)
            self.assertIsNotNone(
                ai._last_generated_test_paper,
                f"Failed to set _last_generated_test_paper for prompt: {p}",
            )
            eval_raw = gyanverse_ui.evaluate_test_paper(ai._last_generated_test_paper, ans_txt)
            eval_formatted = gyanverse_ui.format_tutor_response(eval_raw, student_message=ans_txt)
            self.assertTrue(
                "Total Marks:" in eval_formatted or "Your pasted answers" in eval_formatted,
                f"Evaluation failed for prompt: {p}",
            )
            self.assertIn("Source type: Teacher-authored content.", eval_formatted)


    def test_active_test_paper_restores_after_app_restart(self):
        self.assertIn('ACTIVE_TEST_PAPERS_PATH = DATA_DIR / "active_test_papers.json"', UI)
        self.assertIn("def save_active_test_paper", UI)
        self.assertIn("def restore_active_test_paper", UI)
        self.assertIn("asdict(paper)", UI)
        self.assertIn("TestPaperQuestionItem(**question_payload)", UI)
        self.assertIn("ai_service._last_generated_test_paper = GeneratedTestPaper(**paper_payload)", UI)
        self.assertIn("restored_active_test_paper = restore_active_test_paper()", UI)
        self.assertIn("save_active_test_paper(active_paper)", UI)
        self.assertIn("active_paper.subject", UI)
        self.assertNotIn("active_paper.scope.subject", UI)

        update_context_block = UI.split("def update_context", 1)[1].split("def notify", 1)[0]
        self.assertIn("restore_active_test_paper()", update_context_block)

        new_chat_block = UI.split("def start_new_chat", 1)[1].split("def refresh_cloud_status", 1)[0]
        self.assertIn("ai_service._last_generated_test_paper = None", new_chat_block)

        import json
        import tempfile
        from dataclasses import asdict, fields
        from phase11_ai import GyanVerseAIService
        from phase11_core import GSEBSyllabusRepository, StudentLearningContext, GeneratedTestPaper, TestPaperQuestionItem
        import gyanverse_ui

        repo = GSEBSyllabusRepository(ROOT / "syllabus")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_papers_path = Path(tmpdir) / "active_test_papers.json"
            original_path = gyanverse_ui.ACTIVE_TEST_PAPERS_PATH
            gyanverse_ui.ACTIVE_TEST_PAPERS_PATH = tmp_papers_path
            try:
                ai1 = GyanVerseAIService(syllabus_repository=repo, api_key="mock_key")
                ctx = StudentLearningContext(
                    student_id="s_restart_test",
                    name="Student",
                    board="GSEB",
                    medium="English",
                    standard=8,
                    current_subject="Mathematics",
                    current_chapter="Chapter 1 - Rational Numbers",
                )

                gen_prompt = "Generate Std 8 Mathematics Chapter 1 25-mark test paper."
                _ = ai1.ask_stream(message=gen_prompt, context=ctx)
                active_paper = getattr(ai1, "_last_generated_test_paper", None)
                self.assertIsNotNone(active_paper, "Active test paper should be generated")

                conv_id = "conv_restart_math_8"
                payload = {conv_id: asdict(active_paper)}
                tmp_papers_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                self.assertTrue(tmp_papers_path.exists())

                ai2 = GyanVerseAIService(syllabus_repository=repo, api_key="mock_key")
                self.assertIsNone(ai2._last_generated_test_paper)

                raw = json.loads(tmp_papers_path.read_text(encoding="utf-8")).get(conv_id)
                self.assertIsInstance(raw, dict)
                q_fields = {f.name for f in fields(TestPaperQuestionItem)}
                questions = [TestPaperQuestionItem(**{k: v for k, v in q.items() if k in q_fields}) for q in raw["questions"]]
                p_fields = {f.name for f in fields(GeneratedTestPaper)}
                p_payload = {k: v for k, v in raw.items() if k in p_fields}
                p_payload["questions"] = questions
                ai2._last_generated_test_paper = GeneratedTestPaper(**p_payload)

                ans_msg = "1. -19/13\n2. Left of 0\n3. 9/40"
                eval_resp = ai2.ask_stream(message=ans_msg, context=ctx)

                self.assertIn("Test Evaluation", eval_resp)
                self.assertIn("Standard: 8", eval_resp)
                self.assertIn("Subject: Mathematics", eval_resp)
                self.assertIn("Per-Question Evaluation:", eval_resp)
                self.assertNotIn("could not respond", eval_resp.casefold())

                # Verify context isolation (switching subject invalidates cross-subject active paper)
                ctx_sci = StudentLearningContext(
                    student_id="s_restart_test",
                    name="Student",
                    board="GSEB",
                    medium="English",
                    standard=8,
                    current_subject="Science & Technology",
                    current_chapter="Chapter 1 - Crop Production and Management",
                )
                sci_resp = ai2.ask_stream(message=ans_msg, context=ctx_sci)
                self.assertNotIn("Subject: Mathematics", sci_resp)
                self.assertIsNone(ai2._last_generated_test_paper)
            finally:
                gyanverse_ui.ACTIVE_TEST_PAPERS_PATH = original_path

    def test_live_ui_send_flow_syncs_test_paper_state_and_status_text(self):
        from phase11_ai import GyanVerseAIService
        from phase11_core import GSEBSyllabusRepository, StudentLearningContext
        import gyanverse_ui

        repo = GSEBSyllabusRepository(ROOT / "syllabus")
        ai = GyanVerseAIService(syllabus_repository=repo, api_key="mock_key")
        ctx = StudentLearningContext(
            student_id="s1",
            name="Student",
            board="GSEB",
            medium="English",
            standard=8,
            current_subject="",
            current_chapter="",
        )

        p = "Generate Science Chapter 1 25-mark paper"
        _ = ai.ask_stream(message=p, context=ctx)
        self.assertIsNotNone(ai._last_generated_test_paper)

        ans_txt = (
            "1. Drip irrigation system saves water by delivering water directly to roots.\n"
            "2. Plough and hoe are traditional tools used for preparation of soil.\n"
            "3. Weeds are unwanted plants and weedicides control them."
        )

        eval_raw = gyanverse_ui.evaluate_test_paper(ai._last_generated_test_paper, ans_txt)
        eval_formatted = gyanverse_ui.format_tutor_response(eval_raw, student_message=ans_txt)
        self.assertIn("Total Marks:", eval_formatted)
        self.assertIn("Per-Question Evaluation:", eval_formatted)
        self.assertIn("Source type: Teacher-authored content.", eval_formatted)

    def test_single_ui_send_for_test_paper_appends_exactly_one_tutor_response(self):
        import asyncio
        import flet as ft
        import gyanverse_ui
        from unittest.mock import MagicMock

        tasks = []
        page = MagicMock(spec=ft.Page)
        page.controls = []
        page.overlay = []
        page.dialog = None
        page.width = 1200
        page.height = 800

        def run_task_mock(func, *args, **kwargs):
            t = asyncio.create_task(func(*args, **kwargs))
            tasks.append(t)
            return t

        page.run_task = run_task_mock
        gyanverse_ui.main(page)

        def collect_all(control):
            res = [control]
            if hasattr(control, "controls") and isinstance(control.controls, list):
                for c in control.controls:
                    res.extend(collect_all(c))
            if hasattr(control, "content") and control.content:
                res.extend(collect_all(control.content))
            return res

        all_controls = []
        for call_arg in page.add.call_args_list:
            for top in call_arg[0]:
                all_controls.extend(collect_all(top))

        composers = [c for c in all_controls if isinstance(c, ft.TextField)]
        icon_buttons = [c for c in all_controls if isinstance(c, ft.IconButton)]
        composer = composers[0]
        send_button = icon_buttons[-1]
        queue_fn = send_button.on_click

        async def run_test():
            composer.value = "Generate Science Chapter 1 25-mark test paper"
            # Synchronously trigger both on_click and on_submit
            queue_fn(None)
            queue_fn(None)
            if tasks:
                await asyncio.gather(*tasks)

        asyncio.run(run_test())
        self.assertEqual(len(tasks), 1, "queue_send must schedule exactly 1 task when double-triggered synchronously")

    def test_normal_non_test_prompt_appends_exactly_one_tutor_reply(self):
        import asyncio
        import flet as ft
        import gyanverse_ui
        from unittest.mock import MagicMock

        tasks = []
        page = MagicMock(spec=ft.Page)
        page.controls = []
        page.overlay = []
        page.dialog = None
        page.width = 1200
        page.height = 800

        def run_task_mock(func, *args, **kwargs):
            t = asyncio.create_task(func(*args, **kwargs))
            tasks.append(t)
            return t

        page.run_task = run_task_mock
        gyanverse_ui.main(page)

        def collect_all(control):
            res = [control]
            if hasattr(control, "controls") and isinstance(control.controls, list):
                for c in control.controls:
                    res.extend(collect_all(c))
            if hasattr(control, "content") and control.content:
                res.extend(collect_all(control.content))
            return res

        all_controls = []
        for call_arg in page.add.call_args_list:
            for top in call_arg[0]:
                all_controls.extend(collect_all(top))

        composers = [c for c in all_controls if isinstance(c, ft.TextField)]
        icon_buttons = [c for c in all_controls if isinstance(c, ft.IconButton)]
        composer = composers[0]
        send_button = icon_buttons[-1]
        queue_fn = send_button.on_click

        async def run_test():
            composer.value = "What is crop production?"
            queue_fn(None)
            queue_fn(None)
            if tasks:
                await asyncio.gather(*tasks)

        asyncio.run(run_test())
        self.assertEqual(len(tasks), 1, "queue_send must schedule exactly 1 task when double-triggered synchronously")

    def test_visible_tutor_reply_is_not_duplicated_by_outer_exception_fallback(self):
        self.assertIn("tutor_reply_visible = False", UI)
        self.assertIn("tutor_reply_visible = True", UI)
        self.assertIn("if tutor_reply_visible:", UI)
        self.assertIn('add_message("tutor", fallback)', UI)

    def test_copy_button_uses_full_answer_clipboard_path(self):
        self.assertIn("import subprocess", UI)
        self.assertIn("def copy_full_answer_to_clipboard(full_text: str) -> bool:", UI)
        self.assertIn("[Console]::In.ReadToEnd() | Set-Clipboard", UI)
        self.assertIn("input=text_to_copy", UI)
        self.assertIn('btn_copy.tooltip = "Copied!"', UI)
        self.assertIn('raise RuntimeError("Clipboard unavailable")', UI)

    def test_app_launch_smoke_test_catches_unsupported_flet_kwargs(self):
        import flet as ft
        import gyanverse_ui
        from unittest.mock import MagicMock

        mock_page = MagicMock(spec=ft.Page)
        mock_page.window = MagicMock()
        mock_page.controls = []
        mock_page.drawer = None
        mock_page.update = MagicMock()
        mock_page.add = MagicMock()
        mock_page.run_task = MagicMock()

        try:
            gyanverse_ui.main(mock_page)
        except Exception as exc:
            self.fail(f"App launch failed due to unsupported control attribute or argument: {exc}")

    def test_flet_audio_src_uses_json_serializable_base64_string(self):
        import base64
        import json
        self.assertIn('base64.b64encode(audio_bytes).decode("utf-8")', UI)
        b64 = base64.b64encode(b"RIFF1234WAVE").decode("utf-8")
        self.assertTrue(isinstance(b64, str))
        json.dumps({"src": b64})


if __name__ == "__main__":
    unittest.main()
