from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class TutorEngineError(RuntimeError):
    pass


class TutorEngine:
    """Persistent core tutoring engine independent from the Flet UI."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        ai_client: Any = None,
        model_name: str = "gemini-3.5-flash",
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ai_client = ai_client
        self.model_name = model_name
        self._initialize_database()
        self._seed_curriculum()

    @contextmanager
    def _connect(self):
        """Open a short-lived SQLite connection and always close it on Windows."""
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 12),
                    board TEXT NOT NULL,
                    preferred_language TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curriculum (
                    curriculum_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    board TEXT NOT NULL,
                    grade INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    topic TEXT NOT NULL DEFAULT '',
                    UNIQUE(board, grade, subject, chapter, topic)
                );

                CREATE TABLE IF NOT EXISTS daily_sync (
                    sync_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    studied_on TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS homework (
                    homework_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    checked_at TEXT,
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS homework_results (
                    result_id TEXT PRIMARY KEY,
                    homework_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    feedback_json TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    mastery_percent INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(homework_id) REFERENCES homework(homework_id),
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS learning_interactions (
                    interaction_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    tutor_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS topic_progress (
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    correct_answers INTEGER NOT NULL DEFAULT 0,
                    total_answers INTEGER NOT NULL DEFAULT 0,
                    mastery_percent INTEGER NOT NULL DEFAULT 0,
                    last_studied_at TEXT NOT NULL,
                    PRIMARY KEY(student_id, subject, chapter),
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );
                """
            )

    def _seed_curriculum(self) -> None:
        """Seed an extensible starter map. Full textbook content can be imported later."""
        starter = [
            ("CBSE", 7, "Mathematics", "Integers", "Operations on integers"),
            ("CBSE", 7, "Mathematics", "Fractions and Decimals", "Addition and subtraction"),
            ("CBSE", 7, "Science", "Nutrition in Plants", "Photosynthesis"),
            ("CBSE", 7, "Science", "Heat", "Temperature and transfer of heat"),
            ("CBSE", 7, "English", "Grammar", "Tenses"),
            ("CBSE", 8, "Mathematics", "Rational Numbers", "Properties"),
            ("CBSE", 8, "Mathematics", "Linear Equations", "One variable"),
            ("CBSE", 8, "Science", "Force and Pressure", "Effects of force"),
            ("CBSE", 8, "Science", "Combustion and Flame", "Types of combustion"),
            ("CBSE", 8, "English", "Grammar", "Active and passive voice"),
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO curriculum(board, grade, subject, chapter, topic)
                VALUES (?, ?, ?, ?, ?)
                """,
                starter,
            )

    def ensure_student(
        self,
        *,
        student_id: str,
        name: str,
        grade: int,
        board: str,
        preferred_language: str,
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO students(
                    student_id, name, grade, board, preferred_language, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    name=excluded.name,
                    grade=excluded.grade,
                    board=excluded.board,
                    preferred_language=excluded.preferred_language,
                    updated_at=excluded.updated_at
                """,
                (
                    student_id,
                    name.strip() or "Student",
                    int(grade),
                    board.strip() or "CBSE",
                    preferred_language.strip() or "English (India)",
                    now,
                    now,
                ),
            )

    def _student(self, student_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM students WHERE student_id = ?", (student_id,)
            ).fetchone()
        if row is None:
            raise TutorEngineError(f"Unknown student: {student_id}")
        return row

    def record_daily_sync(
        self,
        *,
        student_id: str,
        subject: str,
        chapter: str,
        topic: str,
    ) -> dict[str, str]:
        self._student(student_id)
        values = [subject.strip(), chapter.strip(), topic.strip()]
        if not all(values):
            raise TutorEngineError("Subject, chapter and topic are required.")

        sync_id = f"sync-{uuid.uuid4().hex[:10]}"
        now = self._now()
        studied_on = now[:10]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_sync(
                    sync_id, student_id, subject, chapter, topic, studied_on, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sync_id, student_id, values[0], values[1], values[2], studied_on, now),
            )
            self._touch_progress(
                connection,
                student_id=student_id,
                subject=values[0],
                chapter=values[1],
                attempts_increment=0,
                correct_increment=0,
                total_increment=0,
            )
        return {
            "sync_id": sync_id,
            "subject": values[0],
            "chapter": values[1],
            "topic": values[2],
            "studied_on": studied_on,
        }

    def _recent_topic(
        self, student_id: str, subject: str, chapter: str
    ) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT topic FROM daily_sync
                WHERE student_id = ? AND lower(subject) = lower(?) AND lower(chapter) = lower(?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (student_id, subject, chapter),
            ).fetchone()
        return row["topic"] if row else None

    @staticmethod
    def _fallback_questions(subject: str, chapter: str, topic: str, count: int) -> list[dict[str, Any]]:
        templates = [
            f"Explain the main idea of {topic or chapter} in your own words.",
            f"Give one correct example related to {topic or chapter}.",
            f"What is one common mistake students make in {topic or chapter}?",
            f"Solve or answer one basic question from {chapter} and show your steps.",
            f"How is {topic or chapter} useful in a real-life situation?",
            f"Write two important facts or rules from {topic or chapter}.",
            f"Create one question of your own from {chapter}, then answer it.",
            f"Compare {topic or chapter} with a related concept from {subject}.",
            f"Describe the steps you would follow to solve a problem from {chapter}.",
            f"State one doubt you still have about {topic or chapter}, then try to resolve it.",
        ]
        return [
            {
                "number": index + 1,
                "question": templates[index],
                "expected_answer": "",
                "keywords": [],
            }
            for index in range(count)
        ]

    @staticmethod
    def _extract_json(text: str) -> Any:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        first_brace = min(
            [pos for pos in (cleaned.find("["), cleaned.find("{")) if pos >= 0],
            default=-1,
        )
        if first_brace > 0:
            cleaned = cleaned[first_brace:]
        return json.loads(cleaned)

    def generate_homework(
        self,
        *,
        student_id: str,
        subject: str,
        chapter: str,
        question_count: int = 5,
    ) -> dict[str, Any]:
        student = self._student(student_id)
        subject = subject.strip()
        chapter = chapter.strip()
        question_count = max(1, min(int(question_count), 10))
        if not subject or not chapter:
            raise TutorEngineError("Subject and chapter are required.")

        topic = self._recent_topic(student_id, subject, chapter) or chapter
        questions: list[dict[str, Any]]

        if self.ai_client is None:
            questions = self._fallback_questions(subject, chapter, topic, question_count)
        else:
            prompt = (
                f"Create exactly {question_count} age-appropriate homework questions for "
                f"Grade {student['grade']} {student['board']} {subject}, chapter {chapter}, "
                f"recent topic {topic}. Use a mix of recall, understanding and application. "
                "Do not make trick questions. Return ONLY valid JSON array. Each item must have "
                'keys: "question", "expected_answer", "keywords". keywords must be an array.'
            )
            try:
                response = self.ai_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                raw = self._extract_json(response.text)
                if not isinstance(raw, list) or len(raw) != question_count:
                    raise ValueError("Unexpected homework JSON shape")
                questions = []
                for index, item in enumerate(raw, start=1):
                    questions.append(
                        {
                            "number": index,
                            "question": str(item["question"]).strip(),
                            "expected_answer": str(item.get("expected_answer", "")).strip(),
                            "keywords": [
                                str(word).strip()
                                for word in item.get("keywords", [])
                                if str(word).strip()
                            ],
                        }
                    )
            except Exception:
                questions = self._fallback_questions(subject, chapter, topic, question_count)

        homework_id = f"hw-{uuid.uuid4().hex[:8]}"
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO homework(
                    homework_id, student_id, subject, chapter, questions_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'assigned', ?)
                """,
                (
                    homework_id,
                    student_id,
                    subject,
                    chapter,
                    json.dumps(questions, ensure_ascii=False),
                    now,
                ),
            )
        return {
            "homework_id": homework_id,
            "student_id": student_id,
            "subject": subject,
            "chapter": chapter,
            "questions": questions,
            "status": "assigned",
        }

    @staticmethod
    def _keyword_score(answer: str, expected: str, keywords: list[str]) -> tuple[bool, str]:
        normalized = re.sub(r"\s+", " ", answer.lower()).strip()
        if not normalized:
            return False, "Answer missing. Try the question before asking for the solution."

        expected_norm = re.sub(r"\s+", " ", expected.lower()).strip()
        keyword_norm = [word.lower() for word in keywords if word.strip()]

        if expected_norm and (
            normalized == expected_norm
            or expected_norm in normalized
            or normalized in expected_norm
        ):
            return True, "Correct. Your answer matches the expected idea."

        if keyword_norm:
            hits = sum(1 for word in keyword_norm if word in normalized)
            ratio = hits / len(keyword_norm)
            if ratio >= 0.6:
                return True, "Mostly correct. You included the key concepts."
            return False, "Not complete yet. Recheck the important terms and explain the logic."

        if len(normalized.split()) >= 5:
            return True, "Reasonable attempt recorded. Teacher verification is recommended."
        return False, "Answer is too short. Explain the idea or steps more clearly."

    def check_homework(
        self,
        *,
        student_id: str,
        homework_id: str,
        answers: list[str],
    ) -> dict[str, Any]:
        self._student(student_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM homework
                WHERE homework_id = ? AND student_id = ?
                """,
                (homework_id.strip(), student_id),
            ).fetchone()
        if row is None:
            raise TutorEngineError("Homework ID not found for this student.")

        questions = json.loads(row["questions_json"])
        normalized_answers = list(answers[: len(questions)])
        normalized_answers.extend([""] * (len(questions) - len(normalized_answers)))

        feedback: list[dict[str, Any]] = []
        score = 0
        for index, (question, answer) in enumerate(
            zip(questions, normalized_answers), start=1
        ):
            correct, message = self._keyword_score(
                answer,
                str(question.get("expected_answer", "")),
                list(question.get("keywords", [])),
            )
            score += int(correct)
            feedback.append(
                {
                    "number": index,
                    "status": "Correct" if correct else "Needs improvement",
                    "feedback": message,
                }
            )

        total = len(questions)
        mastery = round((score / total) * 100) if total else 0
        result_id = f"result-{uuid.uuid4().hex[:10]}"
        now = self._now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO homework_results(
                    result_id, homework_id, student_id, answers_json, feedback_json,
                    score, total, mastery_percent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    homework_id,
                    student_id,
                    json.dumps(normalized_answers, ensure_ascii=False),
                    json.dumps(feedback, ensure_ascii=False),
                    score,
                    total,
                    mastery,
                    now,
                ),
            )
            connection.execute(
                "UPDATE homework SET status='checked', checked_at=? WHERE homework_id=?",
                (now, homework_id),
            )
            self._touch_progress(
                connection,
                student_id=student_id,
                subject=row["subject"],
                chapter=row["chapter"],
                attempts_increment=1,
                correct_increment=score,
                total_increment=total,
            )

        return {
            "result_id": result_id,
            "homework_id": homework_id,
            "score": score,
            "total": total,
            "mastery_percent": mastery,
            "feedback": feedback,
        }

    def _touch_progress(
        self,
        connection: sqlite3.Connection,
        *,
        student_id: str,
        subject: str,
        chapter: str,
        attempts_increment: int,
        correct_increment: int,
        total_increment: int,
    ) -> None:
        existing = connection.execute(
            """
            SELECT attempts, correct_answers, total_answers
            FROM topic_progress
            WHERE student_id=? AND subject=? AND chapter=?
            """,
            (student_id, subject, chapter),
        ).fetchone()

        attempts = attempts_increment
        correct = correct_increment
        total = total_increment
        if existing:
            attempts += existing["attempts"]
            correct += existing["correct_answers"]
            total += existing["total_answers"]

        mastery = round((correct / total) * 100) if total else 0
        connection.execute(
            """
            INSERT INTO topic_progress(
                student_id, subject, chapter, attempts, correct_answers,
                total_answers, mastery_percent, last_studied_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, subject, chapter) DO UPDATE SET
                attempts=excluded.attempts,
                correct_answers=excluded.correct_answers,
                total_answers=excluded.total_answers,
                mastery_percent=excluded.mastery_percent,
                last_studied_at=excluded.last_studied_at
            """,
            (
                student_id,
                subject,
                chapter,
                attempts,
                correct,
                total,
                mastery,
                self._now(),
            ),
        )

    def record_learning_interaction(
        self,
        *,
        student_id: str,
        user_text: str,
        tutor_text: str,
    ) -> None:
        self._student(student_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO learning_interactions(
                    interaction_id, student_id, user_text, tutor_text, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"int-{uuid.uuid4().hex[:10]}",
                    student_id,
                    user_text.strip(),
                    tutor_text.strip(),
                    self._now(),
                ),
            )

    def build_student_context(self, student_id: str) -> str:
        student = self._student(student_id)
        with self._connect() as connection:
            sync_rows = connection.execute(
                """
                SELECT subject, chapter, topic, studied_on
                FROM daily_sync WHERE student_id=?
                ORDER BY created_at DESC LIMIT 5
                """,
                (student_id,),
            ).fetchall()
            progress_rows = connection.execute(
                """
                SELECT subject, chapter, mastery_percent, attempts
                FROM topic_progress WHERE student_id=?
                ORDER BY last_studied_at DESC LIMIT 8
                """,
                (student_id,),
            ).fetchall()

        lines = [
            f"Name: {student['name']}",
            f"Grade: {student['grade']}",
            f"Board: {student['board']}",
            f"Preferred language: {student['preferred_language']}",
        ]
        if sync_rows:
            lines.append("Recent school topics:")
            lines.extend(
                f"- {row['studied_on']}: {row['subject']} / {row['chapter']} / {row['topic']}"
                for row in sync_rows
            )
        if progress_rows:
            lines.append("Progress:")
            lines.extend(
                f"- {row['subject']} / {row['chapter']}: "
                f"{row['mastery_percent']}% mastery after {row['attempts']} checked attempt(s)"
                for row in progress_rows
            )
        return "\n".join(lines)

    def format_progress(self, student_id: str) -> str:
        self._student(student_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject, chapter, attempts, correct_answers,
                       total_answers, mastery_percent, last_studied_at
                FROM topic_progress WHERE student_id=?
                ORDER BY mastery_percent ASC, last_studied_at DESC
                """,
                (student_id,),
            ).fetchall()
        if not rows:
            return "No progress data yet. Record daily learning and complete homework first."
        lines = ["Student progress:"]
        for row in rows:
            lines.append(
                f"{row['subject']} | {row['chapter']} | "
                f"{row['mastery_percent']}% mastery | "
                f"{row['correct_answers']}/{row['total_answers']} correct | "
                f"{row['attempts']} checked attempt(s)"
            )
        return "\n".join(lines)

    def format_today_summary(self, student_id: str) -> str:
        self._student(student_id)
        today = self._now()[:10]
        with self._connect() as connection:
            syncs = connection.execute(
                """
                SELECT subject, chapter, topic FROM daily_sync
                WHERE student_id=? AND studied_on=?
                ORDER BY created_at ASC
                """,
                (student_id, today),
            ).fetchall()
            homework_rows = connection.execute(
                """
                SELECT homework_id, subject, chapter, status
                FROM homework WHERE student_id=? AND substr(created_at, 1, 10)=?
                ORDER BY created_at ASC
                """,
                (student_id, today),
            ).fetchall()

        lines = [f"Today summary ({today}):"]
        if syncs:
            lines.append("School learning:")
            lines.extend(
                f"- {row['subject']} / {row['chapter']}: {row['topic']}" for row in syncs
            )
        else:
            lines.append("No school-learning sync recorded today.")

        if homework_rows:
            lines.append("Homework:")
            lines.extend(
                f"- {row['homework_id']} | {row['subject']} / {row['chapter']} | {row['status']}"
                for row in homework_rows
            )
        else:
            lines.append("No homework generated today.")
        return "\n".join(lines)
