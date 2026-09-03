"""
The AsOS v1 schema.

This reflects the architecture locked in PROJECT.md. Tables map
directly to the agreed data model — see PROJECT.md for the reasoning
behind each design decision (event-sourced mastery, fact provenance,
authority-based conflict resolution, assessment-linked preparedness,
and Canvas-independent task state). Do not casually add columns here;
if the schema needs to change, write an Alembic migration and update
PROJECT.md's decision log in the same change.

DATETIME CONVENTION: every `DateTime` column here is deliberately
plain (no `timezone=True`) and every value stored in one is a naive
UTC datetime produced by `asos.db.base._now()` or an equivalent
explicit conversion. See that function's docstring for why — in short,
SQLite doesn't actually preserve tzinfo across a reload, so pretending
otherwise with `timezone=True` creates a trap rather than a safety net.
"""

from __future__ import annotations

import datetime
import enum as _enum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from asos.db.base import Base, _now
from asos.db.enums import (
    AssessmentType,
    CalendarEventSource,
    CalendarEventType,
    DocumentSourceType,
    FactConfidence,
    FactConflictStatus,
    FactExplicitness,
    MasteryEventType,
    MasteryOutcome,
    NotificationSeverity,
    SourceType,
    SyncChangeType,
    SyncEntityType,
    TaskState,
    TaskType,
)


def _enum_column(py_enum: type[_enum.Enum], **kw):
    """A string-backed enum column with a DB-level CHECK constraint."""
    return mapped_column(SAEnum(py_enum, native_enum=False, validate_strings=True), **kw)


class TimestampMixin:
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(), default=_now, onupdate=_now
    )


# ---------------------------------------------------------------------------
# Courses / assignments / calendar
# ---------------------------------------------------------------------------


class Course(Base, TimestampMixin):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    canvas_course_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    term: Mapped[str | None] = mapped_column(String, nullable=True)
    credit_hours: Mapped[float | None] = mapped_column(nullable=True)

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="course")
    concepts: Mapped[list["Concept"]] = relationship(back_populates="course")
    documents: Mapped[list["Document"]] = relationship(back_populates="course")
    assessments: Mapped[list["Assessment"]] = relationship(back_populates="course")
    tasks: Mapped[list["Task"]] = relationship(back_populates="course")


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    canvas_assignment_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    due_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    points_possible: Mapped[float | None] = mapped_column(nullable=True)
    canvas_status: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Raw Canvas submission status signal, NOT the local task state."
    )
    canvas_synced_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(), nullable=True
    )

    course: Mapped["Course"] = relationship(back_populates="assignments")
    tasks: Mapped[list["Task"]] = relationship(back_populates="related_assignment")


class CalendarEvent(Base, TimestampMixin):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    source: Mapped[CalendarEventSource] = _enum_column(
        CalendarEventSource, nullable=False, default=CalendarEventSource.MANUAL
    )
    external_event_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True, comment="Canvas event id, ICS UID, etc. — unique within its source."
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[CalendarEventType] = _enum_column(CalendarEventType, nullable=False)
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime(), nullable=False)
    end_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)


# ---------------------------------------------------------------------------
# Concepts and mastery (event-sourced)
# ---------------------------------------------------------------------------


class Concept(Base, TimestampMixin):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    parent_concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    course: Mapped["Course"] = relationship(back_populates="concepts")
    parent: Mapped["Concept | None"] = relationship(remote_side=[id])
    mastery_events: Mapped[list["MasteryEvent"]] = relationship(back_populates="concept")


class MasteryEvent(Base):
    """Append-only. Never update or delete a row here — the derived
    mastery score is always computed fresh from this table, so the full
    evidence history (what happened, when, and why the system thinks
    what it thinks) is always reconstructable. See PROJECT.md."""

    __tablename__ = "mastery_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    event_type: Mapped[MasteryEventType] = _enum_column(MasteryEventType, nullable=False)
    outcome: Mapped[MasteryOutcome] = _enum_column(MasteryOutcome, nullable=False)
    outcome_score: Mapped[float] = mapped_column(
        nullable=False, comment="Normalized 0.0-1.0 outcome, used by the derived-score calculation."
    )
    self_rating: Mapped[int | None] = mapped_column(
        nullable=True, comment="1-5, only set when event_type=self_report."
    )
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)
    source_description: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)

    concept: Mapped["Concept"] = relationship(back_populates="mastery_events")


# ---------------------------------------------------------------------------
# Documents / chunks (content ingestion)
# ---------------------------------------------------------------------------


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[DocumentSourceType] = _enum_column(DocumentSourceType, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)

    course: Mapped["Course | None"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_or_slide: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, comment="Reserved for v1's embedding pipeline; unused by the foundation."
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)


# ---------------------------------------------------------------------------
# Sources / facts (provenance + authority)
# ---------------------------------------------------------------------------


class Source(Base):
    """Reference table of source *types* and their default authority
    weight. Per-fact specifics (explicitness, recency) live on Fact
    itself — authority is a function of all three, not this table alone."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[SourceType] = _enum_column(SourceType, unique=True, nullable=False)
    base_authority_weight: Mapped[int] = mapped_column(
        nullable=False, comment="Default weight 1-100; higher wins in the absence of other signals."
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    subject: Mapped[str] = mapped_column(
        String, nullable=False, comment='Free-text key, e.g. "CHEM1010 final exam date".'
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    explicitness: Mapped[FactExplicitness] = _enum_column(FactExplicitness, nullable=False)
    confidence: Mapped[FactConfidence] = _enum_column(FactConfidence, nullable=False)
    verified_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)
    superseded_by_fact_id: Mapped[int | None] = mapped_column(ForeignKey("facts.id"), nullable=True)
    conflict_status: Mapped[FactConflictStatus] = _enum_column(
        FactConflictStatus, nullable=False, default=FactConflictStatus.NONE
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)

    source: Mapped["Source"] = relationship()
    document: Mapped["Document | None"] = relationship()


# ---------------------------------------------------------------------------
# Assessments (preparedness evidence model)
# ---------------------------------------------------------------------------


class Assessment(Base, TimestampMixin):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    assessment_type: Mapped[AssessmentType] = _enum_column(AssessmentType, nullable=False)
    date: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    weight_pct: Mapped[float | None] = mapped_column(nullable=True)

    course: Mapped["Course"] = relationship(back_populates="assessments")
    concept_links: Mapped[list["AssessmentConcept"]] = relationship(back_populates="assessment")
    document_links: Mapped[list["AssessmentDocument"]] = relationship(back_populates="assessment")


class AssessmentConcept(Base):
    __tablename__ = "assessment_concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    importance: Mapped[int | None] = mapped_column(
        nullable=True, comment="1-5; null means even weighting against other linked concepts."
    )

    assessment: Mapped["Assessment"] = relationship(back_populates="concept_links")
    concept: Mapped["Concept"] = relationship()

    __table_args__ = (UniqueConstraint("assessment_id", "concept_id"),)


class AssessmentDocument(Base):
    __tablename__ = "assessment_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)

    assessment: Mapped["Assessment"] = relationship(back_populates="document_links")
    document: Mapped["Document"] = relationship()

    __table_args__ = (UniqueConstraint("assessment_id", "document_id"),)


# ---------------------------------------------------------------------------
# Tasks (local, Canvas-independent completion state)
# ---------------------------------------------------------------------------


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    related_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[TaskType] = _enum_column(TaskType, nullable=False)
    state: Mapped[TaskState] = _enum_column(TaskState, nullable=False, default=TaskState.NOT_STARTED)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)

    course: Mapped["Course | None"] = relationship(back_populates="tasks")
    related_assignment: Mapped["Assignment | None"] = relationship(back_populates="tasks")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    severity: Mapped[NotificationSeverity] = _enum_column(NotificationSeverity, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    related_course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    related_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    related_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assessments.id"), nullable=True
    )
    delivered: Mapped[bool] = mapped_column(default=False, nullable=False)
    delivered_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)


# ---------------------------------------------------------------------------
# Study sessions + episodic memory (semantic memory tier)
# ---------------------------------------------------------------------------


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)

    concept_links: Mapped[list["StudySessionConcept"]] = relationship(back_populates="study_session")


class StudySessionConcept(Base):
    __tablename__ = "study_session_concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id"), nullable=False)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)

    study_session: Mapped["StudySession"] = relationship(back_populates="concept_links")
    concept: Mapped["Concept"] = relationship()

    __table_args__ = (UniqueConstraint("study_session_id", "concept_id"),)


class EpisodicNote(Base):
    """Structured, Claude-written summaries extracted from conversations
    (e.g. "still confused about light reactions despite 3 reviews").
    This is the semantic-memory tier — deliberately NOT raw chat
    transcripts. See PROJECT.md 'Memory system' for the two-tier design."""

    __tablename__ = "episodic_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)


# ---------------------------------------------------------------------------
# Canvas sync audit trail
# ---------------------------------------------------------------------------


class SyncChangeLogEntry(Base):
    """One row per field-level change detected during a Canvas sync.

    This is deliberately separate from the `facts` provenance/authority
    model (Section 6/9 of PROJECT.md): this table is an internal sync
    audit trail ("what changed since last poll, and what was it
    before") — it doesn't carry authority weighting or participate in
    cross-source conflict resolution the way `facts` does. Keeping them
    separate avoids conflating two different concerns that the roadmap
    deliberately scoped as separate milestones."""

    __tablename__ = "sync_change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[SyncEntityType] = _enum_column(SyncEntityType, nullable=False)
    entity_id: Mapped[int] = mapped_column(nullable=False, comment="Local DB id of the affected row.")
    external_id: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="External id from whichever source produced this change (Canvas id, ICS UID, etc.)."
    )
    change_type: Mapped[SyncChangeType] = _enum_column(SyncChangeType, nullable=False)
    field_name: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Null when change_type is created/deleted (whole-entity change)."
    )
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=_now)
