"""Enumerations used across the AsOS schema.

Stored as strings (not native SQL enums) so SQLite migrations never need
an enum-alteration workaround — adding a new value is just a matter of
updating this file, no migration required. SQLAlchemy still enforces a
CHECK constraint at the DB level so bad values can't sneak in via a bug
elsewhere in the app.
"""

from __future__ import annotations

import enum


class CalendarEventType(str, enum.Enum):
    CLASS = "class"
    EXAM = "exam"
    WORK = "work"
    OTHER = "other"


class DocumentSourceType(str, enum.Enum):
    SYLLABUS = "syllabus"
    LECTURE = "lecture"
    NOTES = "notes"
    STUDY_GUIDE = "study_guide"
    OTHER = "other"


class MasteryEventType(str, enum.Enum):
    QUIZ_ANSWER = "quiz_answer"
    STUDY_SESSION = "study_session"
    SELF_REPORT = "self_report"
    MISTAKE_FLAGGED = "mistake_flagged"


class MasteryOutcome(str, enum.Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    SELF_RATED = "self_rated"


class SourceType(str, enum.Enum):
    CANVAS_API = "canvas_api"
    CANVAS_CALENDAR_AUTO = "canvas_calendar_auto"
    SYLLABUS = "syllabus"
    PROFESSOR_ANNOUNCEMENT = "professor_announcement"
    LECTURE_RECORDING = "lecture_recording"
    USER_STATED = "user_stated"
    CLAUDE_INFERRED = "claude_inferred"


class FactExplicitness(str, enum.Enum):
    EXPLICIT_STATEMENT = "explicit_statement"
    INFERRED = "inferred"
    DEFAULT_TEMPLATE = "default_template"


class FactConfidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FactConflictStatus(str, enum.Enum):
    NONE = "none"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


class AssessmentType(str, enum.Enum):
    EXAM = "exam"
    QUIZ = "quiz"
    FINAL = "final"
    OTHER = "other"


class TaskType(str, enum.Enum):
    READING = "reading"
    STUDYING = "studying"
    WORKSHEET = "worksheet"
    PREP = "prep"
    REVIEW = "review"
    OTHER = "other"


class TaskState(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class NotificationSeverity(str, enum.Enum):
    CRITICAL = "critical"
    NOTABLE = "notable"
    AMBIENT = "ambient"


class SyncEntityType(str, enum.Enum):
    COURSE = "course"
    ASSIGNMENT = "assignment"
    CALENDAR_EVENT = "calendar_event"


class SyncChangeType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
