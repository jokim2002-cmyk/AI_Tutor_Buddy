from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from tutor_engine import TutorEngine
from gyanverse_ui_helpers import StudentProfile, safe_text

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
def main(page: ft.Page) -> None:
    page.title = "GyanVerse Academy"
    page.window.width = 1180
    page.window.height = 760
    page.window.min_width = 390
    page.window.min_height = 620
    page.padding = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed="indigo", use_material3=True)

    profile = StudentProfile()
    engine = TutorEngine(db_path=DATA_DIR / "ai_tutor.db")
    engine.ensure_student(
        student_id=profile.student_id,
        name=profile.name,
        grade=profile.grade,
        board=profile.board,
        preferred_language=profile.language,
    )

    content = ft.Container(expand=True, padding=24)
    status = ft.Text("Ready", size=12)
    role_label = ft.Text("Student", weight=ft.FontWeight.BOLD)

    def snackbar(message: str, error: bool = False) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor="red" if error else None)
        page.snack_bar.open = True
        page.update()

    def panel(title: str, body: ft.Control, subtitle: str = "") -> ft.Container:
        return ft.Container(
            content=ft.Column([
                ft.Text(title, size=25, weight=ft.FontWeight.BOLD),
                ft.Text(subtitle, size=13) if subtitle else ft.Container(),
                ft.Divider(),
                body,
            ], spacing=10, scroll=ft.ScrollMode.AUTO),
            expand=True,
        )

    def metric_card(label: str, value: str, hint: str) -> ft.Container:
        return ft.Container(
            content=ft.Column([
                ft.Text(label, size=12),
                ft.Text(value, size=21, weight=ft.FontWeight.BOLD),
                ft.Text(hint, size=11),
            ], spacing=3),
            padding=16,
            border=ft.Border.all(1, "#dddddd"),
            border_radius=12,
            width=220,
        )

    def report_box(title: str, getter: Callable[[], str]) -> ft.Container:
        output = ft.Text("Select Refresh to load the latest report.", selectable=True)
        def refresh(_=None):
            try:
                output.value = safe_text(getter())
                status.value = f"{title} refreshed"
            except Exception as exc:
                output.value = f"Unable to load report: {type(exc).__name__}: {exc}"
            page.update()
        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Text(title, size=18, weight=ft.FontWeight.BOLD), ft.IconButton(ft.Icons.REFRESH, on_click=refresh)]),
                ft.Container(output, padding=12, border=ft.Border.all(1, "#e5e5e5"), border_radius=10),
            ]),
            padding=12,
            border=ft.Border.all(1, "#dddddd"),
            border_radius=12,
        )

    def student_home() -> ft.Control:
        today = engine.format_today_summary(profile.student_id)
        return panel(
            "Student Home",
            ft.Column([
                ft.Row([
                    metric_card("Class", str(profile.grade), profile.board),
                    metric_card("Language", profile.language, "Tutor adapts to you"),
                    metric_card("Learning mode", "Adaptive", "Hints before answers"),
                    metric_card("Privacy", "Protected", "Student-isolated memory"),
                ], spacing=12, run_spacing=12, wrap=True),
                ft.Text("Today", size=20, weight=ft.FontWeight.BOLD),
                ft.Container(ft.Text(safe_text(today), selectable=True), padding=16, border=ft.Border.all(1, "#dddddd"), border_radius=12),
                ft.Text("Quick actions", size=20, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.ElevatedButton("Daily Sync", icon=ft.Icons.SYNC, on_click=lambda _: show_view("sync")),
                    ft.ElevatedButton("Homework", icon=ft.Icons.ASSIGNMENT, on_click=lambda _: show_view("homework")),
                    ft.ElevatedButton("Revision", icon=ft.Icons.REPLAY, on_click=lambda _: show_view("revision")),
                    ft.ElevatedButton("Progress", icon=ft.Icons.INSIGHTS, on_click=lambda _: show_view("progress")),
                ], spacing=10, wrap=True),
            ], spacing=18),
            "Welcome to your safe, hint-first learning space.",
        )

    def sync_view() -> ft.Control:
        subject=ft.TextField(label="Subject", value="Mathematics")
        chapter=ft.TextField(label="Chapter", value="Fractions and Decimals")
        topic=ft.TextField(label="What was taught today?", multiline=True, min_lines=2)
        result=ft.Text(selectable=True)
        def save(_):
            try:
                if not subject.value.strip() or not chapter.value.strip() or not topic.value.strip():
                    raise ValueError("All fields are required.")
                data=engine.record_daily_sync(student_id=profile.student_id, subject=subject.value, chapter=chapter.value, topic=topic.value)
                result.value=f"Saved: {data['subject']} â†’ {data['chapter']} â†’ {data['topic']}"
                snackbar("Daily learning saved")
            except Exception as exc:
                snackbar(str(exc), True)
            page.update()
        return panel("Daily Sync", ft.Column([subject, chapter, topic, ft.ElevatedButton("Save today's learning", icon=ft.Icons.SAVE, on_click=save), result], spacing=12), "Tell GyanVerse what school covered today.")

    def homework_view() -> ft.Control:
        subject=ft.TextField(label="Subject", value="Mathematics")
        chapter=ft.TextField(label="Chapter", value="Fractions and Decimals")
        count=ft.Dropdown(label="Questions", value="5", options=[ft.dropdown.Option(str(n)) for n in range(1,11)])
        output=ft.Text(selectable=True)
        def generate(_):
            try:
                hw=engine.generate_homework(student_id=profile.student_id, subject=subject.value, chapter=chapter.value, question_count=int(count.value))
                lines=[f"Homework ID: {hw['homework_id']}", f"Difficulty: {hw['difficulty']}", ""]
                lines += [f"{q['number']}. {q['question']}" for q in hw['questions']]
                output.value="\n".join(lines)
                snackbar("Homework generated")
            except Exception as exc:
                output.value=f"Error: {exc}"
            page.update()
        return panel("Homework Studio", ft.Column([ft.ResponsiveRow([ft.Container(subject, col=5), ft.Container(chapter, col=5), ft.Container(count, col=2)]), ft.ElevatedButton("Generate adaptive homework", icon=ft.Icons.AUTO_AWESOME, on_click=generate), ft.Container(output, padding=14, border=ft.Border.all(1,"#dddddd"), border_radius=10)], spacing=14), "Practice adjusts to the student's current mastery.")

    def progress_view() -> ft.Control:
        return panel("Progress & Learning Timeline", ft.Column([
            report_box("Progress summary", lambda: engine.format_progress(profile.student_id)),
            report_box("Today's summary", lambda: engine.format_today_summary(profile.student_id)),
        ], spacing=16), "Evidence-based progress without permanent labels.")

    def revision_view() -> ft.Control:
        return panel("Revision Centre", ft.Column([
            report_box("Revision queue", lambda: engine.format_revision_queue(profile.student_id)),
            report_box("Misconception patterns", lambda: engine.format_misconceptions(profile.student_id)),
        ], spacing=16), "Topics are prioritised using learning evidence and spaced revision.")

    def tutor_view() -> ft.Control:
        transcript=ft.ListView(expand=True, spacing=10, auto_scroll=True)
        prompt=ft.TextField(hint_text="Ask a question...", expand=True)
        def add(who: str, message: str):
            transcript.controls.append(ft.Container(ft.Text(f"{who}: {message}", selectable=True), padding=10, border=ft.Border.all(1,"#e1e1e1"), border_radius=10))
        add("Tutor", "I am ready. I will guide with hints before giving final answers. Core reports work offline; live AI chat needs Gemini configuration.")
        def send(_):
            value=(prompt.value or "").strip()
            if not value: return
            add("Student", value); prompt.value=""
            add("Tutor", "Live AI chat remains available through the legacy voice tutor entry point. Use the study tools here for offline-safe learning workflows.")
            page.update()
        return panel("AI Tutor Classroom", ft.Column([transcript, ft.Row([prompt, ft.IconButton(ft.Icons.MIC, tooltip="Voice tutor is available in legacy mode"), ft.ElevatedButton("Send", on_click=send)])], expand=True), "Student classroom shell with safe operational fallback.")

    def parent_view() -> ft.Control:
        return panel("Parent / Guardian Portal", ft.Column([
            ft.Row([metric_card("Linked children", "1", "Privacy-isolated"), metric_card("Alerts", "Safe", "No shame or sibling comparisons"), metric_card("Reports", "Daily / Weekly", "Support-focused language")], spacing=12, wrap=True),
            report_box("Child progress", lambda: engine.format_progress(profile.student_id)),
            report_box("Home revision support", lambda: engine.format_revision_queue(profile.student_id)),
        ], spacing=16), "Clear, supportive information for home learning.")

    def teacher_view() -> ft.Control:
        return panel("Teacher Dashboard", ft.Column([
            ft.Row([metric_card("Student", profile.name, f"Class {profile.grade}"), metric_card("Teaching policy", "Hint first", "Explainable decisions"), metric_card("Classroom", "Ready", "Orchestrator enabled")], spacing=12, wrap=True),
            report_box("Learning evidence", lambda: engine.format_progress(profile.student_id)),
            report_box("Intervention queue", lambda: engine.format_misconceptions(profile.student_id)),
        ], spacing=16), "Actionable evidence for the Class Teacher and subject teachers.")

    def principal_view() -> ft.Control:
        return panel("Principal Dashboard", ft.Column([
            ft.Row([metric_card("Academy core", "Operational", "193 baseline tests"), metric_card("Safety", "Enforced", "Privacy and dignity gates"), metric_card("Release", "RC1", "Backend release evidence complete")], spacing=12, wrap=True),
            ft.Container(ft.Column([
                ft.Text("Academy capabilities", size=18, weight=ft.FontWeight.BOLD),
                ft.Text("Student Analyzer â€¢ Teacher Reasoning â€¢ Strategy Selector â€¢ Classroom Orchestrator â€¢ Long-Term Memory â€¢ Learning Intelligence â€¢ Guardian Reporting â€¢ Stabilization"),
            ]), padding=16, border=ft.Border.all(1,"#dddddd"), border_radius=12),
            report_box("Current learner overview", lambda: engine.format_today_summary(profile.student_id)),
        ], spacing=16), "School-wide operational overview and ethical governance.")

    def settings_view() -> ft.Control:
        return panel("Settings & Privacy", ft.Column([
            ft.TextField(label="Student name", value=profile.name, disabled=True),
            ft.TextField(label="Student ID", value=profile.student_id, disabled=True),
            ft.TextField(label="Database", value=str(engine.db_path), disabled=True),
            ft.Switch(label="Use accessible large controls", value=True),
            ft.Switch(label="Allow voice features when configured", value=True),
            ft.Text("Sensitive data and API secrets are never committed to Git. Local learning data is stored in the data folder."),
        ], spacing=12), "Local configuration, accessibility, and data transparency.")

    builders={
        "home": student_home, "tutor": tutor_view, "sync": sync_view,
        "homework": homework_view, "revision": revision_view, "progress": progress_view,
        "parent": parent_view, "teacher": teacher_view, "principal": principal_view,
        "settings": settings_view,
    }

    def show_view(key: str):
        content.content = builders.get(key, student_home)()
        page.update()

    nav = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=92,
        min_extended_width=220,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="Home"),
            ft.NavigationRailDestination(icon=ft.Icons.SCHOOL_OUTLINED, selected_icon=ft.Icons.SCHOOL, label="Tutor"),
            ft.NavigationRailDestination(icon=ft.Icons.SYNC, label="Daily Sync"),
            ft.NavigationRailDestination(icon=ft.Icons.ASSIGNMENT_OUTLINED, selected_icon=ft.Icons.ASSIGNMENT, label="Homework"),
            ft.NavigationRailDestination(icon=ft.Icons.REPLAY, label="Revision"),
            ft.NavigationRailDestination(icon=ft.Icons.INSIGHTS, label="Progress"),
            ft.NavigationRailDestination(icon=ft.Icons.FAMILY_RESTROOM, label="Parent"),
            ft.NavigationRailDestination(icon=ft.Icons.CAST_FOR_EDUCATION, label="Teacher"),
            ft.NavigationRailDestination(icon=ft.Icons.ADMIN_PANEL_SETTINGS, label="Principal"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS, label="Settings"),
        ],
    )
    keys=["home","tutor","sync","homework","revision","progress","parent","teacher","principal","settings"]
    def nav_change(event):
        key=keys[event.control.selected_index]
        role_label.value = "Student" if key in keys[:6] else key.title()
        show_view(key)
    nav.on_change=nav_change

    topbar=ft.Container(
        content=ft.Row([
            ft.Column([ft.Text("GyanVerse Academy", size=22, weight=ft.FontWeight.BOLD), ft.Text("AI Tutor Buddy learning platform", size=11)], spacing=0),
            ft.Container(expand=True), role_label, ft.VerticalDivider(), status,
        ]), padding=ft.Padding(left=20, top=12, right=20, bottom=12), border=ft.Border(bottom=ft.BorderSide(1, "#dddddd"))
    )
    page.add(ft.Column([topbar, ft.Row([nav, ft.VerticalDivider(width=1), content], expand=True)], expand=True, spacing=0))
    show_view("home")


if __name__ == "__main__":
    ft.run(main)


