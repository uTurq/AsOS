from __future__ import annotations

from asos.assessments.preparedness import AssessmentPreparedness, ConceptPreparedness
from asos.db.enums import NotificationSeverity, TaskState, TaskType
from asos.db.models import Assessment, Concept, Task
from asos.mastery.scoring import ConceptMasteryResult, MasteryLevel
from asos.notifications.classification import classify_assessment_urgency, classify_task_urgency


def _prep_with_levels(*levels: MasteryLevel) -> AssessmentPreparedness:
    concepts = [
        ConceptPreparedness(
            concept=Concept(name=f"concept-{i}"),
            importance=None,
            mastery=ConceptMasteryResult(concept_id=i, level=level, score=None, event_count=0, last_reviewed=None, events=[]),
        )
        for i, level in enumerate(levels)
    ]
    return AssessmentPreparedness(assessment=Assessment(name="Exam 1"), concepts=concepts)


def test_well_prepared_assessment_produces_no_notification():
    prep = _prep_with_levels(MasteryLevel.STRONG, MasteryLevel.STRONG)
    assert classify_assessment_urgency(prep, hours_until=24) is None


def test_weak_spots_within_48h_is_critical():
    prep = _prep_with_levels(MasteryLevel.STRONG, MasteryLevel.WEAK)
    assert classify_assessment_urgency(prep, hours_until=36) == NotificationSeverity.CRITICAL


def test_weak_spots_within_72h_is_notable():
    prep = _prep_with_levels(MasteryLevel.WEAK)
    assert classify_assessment_urgency(prep, hours_until=60) == NotificationSeverity.NOTABLE


def test_weak_spots_within_a_week_is_ambient():
    prep = _prep_with_levels(MasteryLevel.NO_EVIDENCE)
    assert classify_assessment_urgency(prep, hours_until=150) == NotificationSeverity.AMBIENT


def test_weak_spots_far_in_future_produces_no_notification():
    prep = _prep_with_levels(MasteryLevel.WEAK)
    assert classify_assessment_urgency(prep, hours_until=400) is None


def test_past_assessment_produces_no_notification():
    prep = _prep_with_levels(MasteryLevel.WEAK)
    assert classify_assessment_urgency(prep, hours_until=-5) is None


def test_task_due_soon_and_not_started_is_critical():
    task = Task(title="Do worksheet", task_type=TaskType.WORKSHEET, state=TaskState.NOT_STARTED)
    assert classify_task_urgency(task, hours_until=8) == NotificationSeverity.CRITICAL


def test_task_due_soon_but_already_done_produces_no_notification():
    task = Task(title="Do worksheet", task_type=TaskType.WORKSHEET, state=TaskState.DONE)
    assert classify_task_urgency(task, hours_until=8) is None


def test_task_due_soon_but_skipped_produces_no_notification():
    task = Task(title="Optional reading", task_type=TaskType.READING, state=TaskState.SKIPPED)
    assert classify_task_urgency(task, hours_until=2) is None


def test_task_due_in_a_few_days_is_notable():
    task = Task(title="Read chapter 5", task_type=TaskType.READING, state=TaskState.NOT_STARTED)
    assert classify_task_urgency(task, hours_until=48) == NotificationSeverity.NOTABLE


def test_blocked_task_due_soon_still_notifies():
    task = Task(title="Lab report", task_type=TaskType.WORKSHEET, state=TaskState.BLOCKED, blocked_reason="waiting on data")
    assert classify_task_urgency(task, hours_until=6) == NotificationSeverity.CRITICAL
