from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

from .student_analyzer import StudentContext


def _safe_float(value: Any):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def context_from_mapping(data: Mapping[str, Any]) -> StudentContext:
    """Converts database/API-shaped mappings into the stable analyzer contract."""

    helpful = data.get("helpful_methods") or ()
    if isinstance(helpful, str):
        helpful = tuple(part.strip() for part in helpful.split(",") if part.strip())
    else:
        helpful = tuple(str(item) for item in helpful)

    messages = data.get("recent_messages") or ()
    if isinstance(messages, str):
        messages = (messages,)
    else:
        messages = tuple(str(item) for item in messages)

    class_level = data.get("class_level")
    if class_level in (None, ""):
        normalized_class = None
    else:
        try:
            normalized_class = int(class_level)
        except (TypeError, ValueError):
            normalized_class = None

    days = data.get("days_since_last_practice")
    normalized_days = None if days in (None, "") else _safe_int(days)

    return StudentContext(
        student_id=str(data.get("student_id") or "default"),
        class_level=normalized_class,
        preferred_language=str(data.get("preferred_language") or "auto"),
        subject=str(data.get("subject") or ""),
        topic=str(data.get("topic") or ""),
        recent_accuracy=_safe_float(data.get("recent_accuracy")),
        attempts_on_topic=_safe_int(data.get("attempts_on_topic")),
        hints_used=_safe_int(data.get("hints_used")),
        repeated_mistakes=_safe_int(data.get("repeated_mistakes")),
        days_since_last_practice=normalized_days,
        prior_mastery=_safe_float(data.get("prior_mastery")),
        helpful_methods=helpful,
        recent_messages=messages,
    )
