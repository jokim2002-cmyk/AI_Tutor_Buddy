from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

                CREATE TABLE IF NOT EXISTS diagnostic_assessments (
                    diagnostic_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    checked_at TEXT,
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS diagnostic_results (
                    result_id TEXT PRIMARY KEY,
                    diagnostic_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    feedback_json TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    mastery_percent INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(diagnostic_id) REFERENCES diagnostic_assessments(diagnostic_id),
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS misconceptions (
                    misconception_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    misconception_type TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(student_id, subject, chapter, misconception_type),
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS difficulty_state (
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(student_id, subject, chapter),
                    FOREIGN KEY(student_id) REFERENCES students(student_id)
                );

                CREATE TABLE IF NOT EXISTS revision_queue (
                    revision_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    due_on TEXT NOT NULL,
                    interval_days INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(student_id, subject, chapter, due_on),
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
        difficulty = self.get_adaptive_difficulty(
            student_id=student_id,
            subject=subject,
            chapter=chapter,
        )
        questions: list[dict[str, Any]]

        if self.ai_client is None:
            questions = self._fallback_questions(subject, chapter, topic, question_count)
        else:
            prompt = (
                f"Create exactly {question_count} age-appropriate homework questions for "
                f"Grade {student['grade']} {student['board']} {subject}, chapter {chapter}, "
                f"recent topic {topic}. Target difficulty: {difficulty}. "
                "Foundation means simpler guided questions, standard means mixed understanding and "
                "application, challenge means multi-step application. "
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
            "difficulty": difficulty,
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
            difficulty = self._update_difficulty_state(
                connection,
                student_id=student_id,
                subject=row["subject"],
                chapter=row["chapter"],
                mastery_percent=mastery,
            )
            revision = self._schedule_revision(
                connection,
                student_id=student_id,
                subject=row["subject"],
                chapter=row["chapter"],
                mastery_percent=mastery,
                reason="Homework result",
            )
            for question, answer, item_feedback in zip(
                questions, normalized_answers, feedback
            ):
                if item_feedback["status"] != "Correct":
                    misconception_type, evidence = self._classify_misconception(
                        answer=answer,
                        expected=str(question.get("expected_answer", "")),
                        keywords=list(question.get("keywords", [])),
                    )
                    self._record_misconception(
                        connection,
                        student_id=student_id,
                        subject=row["subject"],
                        chapter=row["chapter"],
                        misconception_type=misconception_type,
                        evidence=evidence,
                    )

        return {
            "result_id": result_id,
            "homework_id": homework_id,
            "score": score,
            "total": total,
            "mastery_percent": mastery,
            "feedback": feedback,
            "difficulty": difficulty,
            "revision_due_on": revision["due_on"],
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


    @staticmethod
    def _difficulty_from_mastery(mastery_percent: int) -> str:
        if mastery_percent < 40:
            return "foundation"
        if mastery_percent < 75:
            return "standard"
        return "challenge"

    def get_adaptive_difficulty(
        self,
        *,
        student_id: str,
        subject: str,
        chapter: str,
    ) -> str:
        self._student(student_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT difficulty FROM difficulty_state
                WHERE student_id=? AND subject=? AND chapter=?
                """,
                (student_id, subject.strip(), chapter.strip()),
            ).fetchone()
            if row:
                return row["difficulty"]

            progress = connection.execute(
                """
                SELECT mastery_percent FROM topic_progress
                WHERE student_id=? AND subject=? AND chapter=?
                """,
                (student_id, subject.strip(), chapter.strip()),
            ).fetchone()

        mastery = progress["mastery_percent"] if progress else 0
        return self._difficulty_from_mastery(mastery)

    def _update_difficulty_state(
        self,
        connection: sqlite3.Connection,
        *,
        student_id: str,
        subject: str,
        chapter: str,
        mastery_percent: int,
    ) -> str:
        difficulty = self._difficulty_from_mastery(mastery_percent)
        connection.execute(
            """
            INSERT INTO difficulty_state(
                student_id, subject, chapter, difficulty, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, subject, chapter) DO UPDATE SET
                difficulty=excluded.difficulty,
                updated_at=excluded.updated_at
            """,
            (student_id, subject, chapter, difficulty, self._now()),
        )
        return difficulty

    def _schedule_revision(
        self,
        connection: sqlite3.Connection,
        *,
        student_id: str,
        subject: str,
        chapter: str,
        mastery_percent: int,
        reason: str,
    ) -> dict[str, Any]:
        if mastery_percent < 40:
            interval_days = 1
        elif mastery_percent < 75:
            interval_days = 3
        elif mastery_percent < 90:
            interval_days = 7
        else:
            interval_days = 14

        due_on = (
            datetime.now(timezone.utc) + timedelta(days=interval_days)
        ).date().isoformat()
        revision_id = f"rev-{uuid.uuid4().hex[:10]}"
        connection.execute(
            """
            INSERT OR IGNORE INTO revision_queue(
                revision_id, student_id, subject, chapter, reason, due_on,
                interval_days, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                revision_id,
                student_id,
                subject,
                chapter,
                reason,
                due_on,
                interval_days,
                self._now(),
            ),
        )
        return {
            "revision_id": revision_id,
            "due_on": due_on,
            "interval_days": interval_days,
        }

    @staticmethod
    def _classify_misconception(
        *,
        answer: str,
        expected: str,
        keywords: list[str],
    ) -> tuple[str, str]:
        normalized = re.sub(r"\s+", " ", answer.lower()).strip()
        if not normalized:
            return "no_attempt", "Student left the answer blank."

        expected_norm = re.sub(r"\s+", " ", expected.lower()).strip()
        keyword_norm = [word.lower() for word in keywords if word.strip()]

        if len(normalized.split()) <= 3:
            return "incomplete_reasoning", "Answer was too short to show understanding."

        if keyword_norm and not any(word in normalized for word in keyword_norm):
            return "concept_gap", "Answer missed all expected key concepts."

        number_tokens = re.findall(r"-?\d+(?:\.\d+)?", normalized)
        expected_numbers = re.findall(r"-?\d+(?:\.\d+)?", expected_norm)
        if expected_numbers and number_tokens and number_tokens != expected_numbers:
            return "calculation_error", "Numeric result did not match the expected result."

        if expected_norm and normalized != expected_norm:
            return "partial_understanding", "Student showed some understanding but not the full expected idea."

        return "needs_review", "Answer needs teacher review."

    def _record_misconception(
        self,
        connection: sqlite3.Connection,
        *,
        student_id: str,
        subject: str,
        chapter: str,
        misconception_type: str,
        evidence: str,
    ) -> None:
        now = self._now()
        connection.execute(
            """
            INSERT INTO misconceptions(
                misconception_id, student_id, subject, chapter,
                misconception_type, evidence, occurrence_count, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(student_id, subject, chapter, misconception_type)
            DO UPDATE SET
                evidence=excluded.evidence,
                occurrence_count=misconceptions.occurrence_count + 1,
                last_seen_at=excluded.last_seen_at
            """,
            (
                f"mis-{uuid.uuid4().hex[:10]}",
                student_id,
                subject,
                chapter,
                misconception_type,
                evidence[:500],
                now,
            ),
        )

    @staticmethod
    def _fallback_diagnostic_questions(subject: str, count: int) -> list[dict[str, Any]]:
        bank = {
            "mathematics": [
                ("What is -7 + 12?", "5", ["5"]),
                ("Simplify 3/4 + 1/4.", "1", ["1"]),
                ("Solve: 2x + 3 = 11.", "4", ["4"]),
                ("What is 15% of 200?", "30", ["30"]),
                ("A rectangle is 8 cm long and 5 cm wide. Find its area.", "40", ["40"]),
                ("Write 0.75 as a fraction in simplest form.", "3/4", ["3/4"]),
                ("Find the mean of 4, 6 and 8.", "6", ["6"]),
                ("What is the next number: 2, 4, 8, 16, ?", "32", ["32"]),
            ],
            "science": [
                ("What process do green plants use to make food?", "photosynthesis", ["photosynthesis"]),
                ("Name the force that pulls objects toward Earth.", "gravity", ["gravity"]),
                ("What is the boiling point of water in Celsius at sea level?", "100", ["100"]),
                ("Which organ pumps blood through the body?", "heart", ["heart"]),
                ("Is air a mixture or a pure substance?", "mixture", ["mixture"]),
                ("What form of energy is stored in food?", "chemical energy", ["chemical", "energy"]),
                ("Why does a metal spoon feel hot in tea?", "conduction", ["conduction"]),
                ("Name one renewable source of energy.", "solar energy", ["solar"]),
            ],
            "english": [
                ("Identify the verb: The child runs quickly.", "runs", ["runs"]),
                ("Change to past tense: She walks to school.", "She walked to school.", ["walked"]),
                ("Give the plural of child.", "children", ["children"]),
                ("Choose the article: ___ apple.", "an", ["an"]),
                ("What is the opposite of ancient?", "modern", ["modern"]),
                ("Correct the sentence: He go to school.", "He goes to school.", ["goes"]),
                ("Identify the adjective: It is a beautiful flower.", "beautiful", ["beautiful"]),
                ("Change to passive voice: Ravi wrote the letter.", "The letter was written by Ravi.", ["letter", "written", "Ravi"]),
            ],
        }
        selected = bank.get(subject.lower(), bank["mathematics"])[:count]
        return [
            {
                "number": index + 1,
                "chapter": "Baseline",
                "question": question,
                "expected_answer": expected,
                "keywords": keywords,
            }
            for index, (question, expected, keywords) in enumerate(selected)
        ]

    def generate_diagnostic(
        self,
        *,
        student_id: str,
        subject: str,
        question_count: int = 5,
    ) -> dict[str, Any]:
        student = self._student(student_id)
        subject = subject.strip()
        question_count = max(3, min(int(question_count), 8))
        if not subject:
            raise TutorEngineError("Subject is required.")

        questions: list[dict[str, Any]]
        if self.ai_client is None:
            questions = self._fallback_diagnostic_questions(subject, question_count)
        else:
            prompt = (
                f"Create exactly {question_count} short baseline diagnostic questions for "
                f"Grade {student['grade']} {student['board']} {subject}. Cover different core skills. "
                "Return ONLY valid JSON array. Each item must contain chapter, question, "
                "expected_answer, and keywords array. Avoid ambiguous questions."
            )
            try:
                response = self.ai_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                raw = self._extract_json(response.text)
                if not isinstance(raw, list) or len(raw) != question_count:
                    raise ValueError("Unexpected diagnostic JSON shape")
                questions = [
                    {
                        "number": index,
                        "chapter": str(item.get("chapter", "Baseline")).strip() or "Baseline",
                        "question": str(item["question"]).strip(),
                        "expected_answer": str(item.get("expected_answer", "")).strip(),
                        "keywords": [
                            str(word).strip()
                            for word in item.get("keywords", [])
                            if str(word).strip()
                        ],
                    }
                    for index, item in enumerate(raw, start=1)
                ]
            except Exception:
                questions = self._fallback_diagnostic_questions(subject, question_count)

        diagnostic_id = f"diag-{uuid.uuid4().hex[:8]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO diagnostic_assessments(
                    diagnostic_id, student_id, subject, questions_json, status, created_at
                ) VALUES (?, ?, ?, ?, 'assigned', ?)
                """,
                (
                    diagnostic_id,
                    student_id,
                    subject,
                    json.dumps(questions, ensure_ascii=False),
                    self._now(),
                ),
            )
        return {
            "diagnostic_id": diagnostic_id,
            "subject": subject,
            "questions": questions,
            "status": "assigned",
        }

    def check_diagnostic(
        self,
        *,
        student_id: str,
        diagnostic_id: str,
        answers: list[str],
    ) -> dict[str, Any]:
        self._student(student_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM diagnostic_assessments
                WHERE diagnostic_id=? AND student_id=?
                """,
                (diagnostic_id.strip(), student_id),
            ).fetchone()
        if row is None:
            raise TutorEngineError("Diagnostic ID not found for this student.")

        questions = json.loads(row["questions_json"])
        normalized_answers = list(answers[: len(questions)])
        normalized_answers.extend([""] * (len(questions) - len(normalized_answers)))

        score = 0
        feedback: list[dict[str, Any]] = []
        chapter_totals: dict[str, list[int]] = {}

        with self._connect() as connection:
            for index, (question, answer) in enumerate(
                zip(questions, normalized_answers), start=1
            ):
                correct, message = self._keyword_score(
                    answer,
                    str(question.get("expected_answer", "")),
                    list(question.get("keywords", [])),
                )
                score += int(correct)
                chapter = str(question.get("chapter", "Baseline"))
                chapter_totals.setdefault(chapter, [0, 0])
                chapter_totals[chapter][0] += int(correct)
                chapter_totals[chapter][1] += 1

                misconception_type = None
                if not correct:
                    misconception_type, evidence = self._classify_misconception(
                        answer=answer,
                        expected=str(question.get("expected_answer", "")),
                        keywords=list(question.get("keywords", [])),
                    )
                    self._record_misconception(
                        connection,
                        student_id=student_id,
                        subject=row["subject"],
                        chapter=chapter,
                        misconception_type=misconception_type,
                        evidence=evidence,
                    )

                feedback.append(
                    {
                        "number": index,
                        "status": "Correct" if correct else "Needs improvement",
                        "feedback": message,
                        "misconception": misconception_type,
                    }
                )

            for chapter, (correct_count, total_count) in chapter_totals.items():
                chapter_mastery = round((correct_count / total_count) * 100)
                self._touch_progress(
                    connection,
                    student_id=student_id,
                    subject=row["subject"],
                    chapter=chapter,
                    attempts_increment=1,
                    correct_increment=correct_count,
                    total_increment=total_count,
                )
                self._update_difficulty_state(
                    connection,
                    student_id=student_id,
                    subject=row["subject"],
                    chapter=chapter,
                    mastery_percent=chapter_mastery,
                )
                self._schedule_revision(
                    connection,
                    student_id=student_id,
                    subject=row["subject"],
                    chapter=chapter,
                    mastery_percent=chapter_mastery,
                    reason="Diagnostic baseline result",
                )

            total = len(questions)
            mastery = round((score / total) * 100) if total else 0
            result_id = f"diag-result-{uuid.uuid4().hex[:10]}"
            now = self._now()
            connection.execute(
                """
                INSERT INTO diagnostic_results(
                    result_id, diagnostic_id, student_id, answers_json,
                    feedback_json, score, total, mastery_percent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    diagnostic_id,
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
                """
                UPDATE diagnostic_assessments
                SET status='checked', checked_at=?
                WHERE diagnostic_id=?
                """,
                (now, diagnostic_id),
            )

        return {
            "result_id": result_id,
            "diagnostic_id": diagnostic_id,
            "score": score,
            "total": total,
            "mastery_percent": mastery,
            "feedback": feedback,
        }

    def format_misconceptions(self, student_id: str) -> str:
        self._student(student_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject, chapter, misconception_type, occurrence_count, evidence
                FROM misconceptions WHERE student_id=?
                ORDER BY occurrence_count DESC, last_seen_at DESC
                """,
                (student_id,),
            ).fetchall()
        if not rows:
            return "No misconception patterns recorded yet."
        lines = ["Misconception patterns:"]
        for row in rows:
            lines.append(
                f"{row['subject']} | {row['chapter']} | "
                f"{row['misconception_type']} | seen {row['occurrence_count']} time(s)"
            )
        return "\n".join(lines)

    def format_revision_queue(self, student_id: str) -> str:
        self._student(student_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision_id, subject, chapter, due_on, interval_days, reason
                FROM revision_queue
                WHERE student_id=? AND status='pending'
                ORDER BY due_on ASC
                """,
                (student_id,),
            ).fetchall()
        if not rows:
            return "No pending revision is scheduled."
        lines = ["Revision queue:"]
        for row in rows:
            lines.append(
                f"{row['revision_id']} | {row['subject']} / {row['chapter']} | "
                f"due {row['due_on']} | after {row['interval_days']} day(s)"
            )
        return "\n".join(lines)

    def complete_revision(
        self,
        *,
        student_id: str,
        revision_id: str,
    ) -> None:
        self._student(student_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE revision_queue
                SET status='completed', completed_at=?
                WHERE revision_id=? AND student_id=? AND status='pending'
                """,
                (self._now(), revision_id.strip(), student_id),
            )
            if cursor.rowcount == 0:
                raise TutorEngineError("Pending revision ID not found.")

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
            misconception_rows = connection.execute(
                """
                SELECT subject, chapter, misconception_type, occurrence_count
                FROM misconceptions WHERE student_id=?
                ORDER BY occurrence_count DESC, last_seen_at DESC LIMIT 5
                """,
                (student_id,),
            ).fetchall()
            revision_rows = connection.execute(
                """
                SELECT subject, chapter, due_on
                FROM revision_queue
                WHERE student_id=? AND status='pending'
                ORDER BY due_on ASC LIMIT 5
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
        if misconception_rows:
            lines.append("Known misconception patterns:")
            lines.extend(
                f"- {row['subject']} / {row['chapter']}: "
                f"{row['misconception_type']} ({row['occurrence_count']} occurrence(s))"
                for row in misconception_rows
            )
        if revision_rows:
            lines.append("Pending revisions:")
            lines.extend(
                f"- {row['subject']} / {row['chapter']} due {row['due_on']}"
                for row in revision_rows
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
