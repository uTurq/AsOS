"""
Preparedness: "how prepared am I for Exam 1?" answered honestly.

Locked design requirement: this must be explainable from real mastery
evidence for the concepts actually covered on the assessment — never a
single fabricated aggregate. Concretely that means:
  - Concepts are bucketed into strong/developing/weak/no-evidence,
    each traceable back to compute_concept_mastery's raw events.
  - The headline "overall score" is computed only from concepts that
    HAVE evidence — a concept nobody has ever studied does not get
    silently treated as "0% mastered" (that would be fabricating a
    confidence level this system doesn't actually have).
  - Coverage (how much of the assessment, by importance-weight, has
    ANY evidence at all) is reported separately, specifically so a
    high "overall score" computed from only the 20% of material
    someone has studied doesn't get mistaken for full readiness.
"""

from __future__ import annotations

import dataclasses
import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.db.models import Assessment, AssessmentConcept, Concept
from asos.mastery.scoring import ConceptMasteryResult, MasteryLevel, compute_concept_mastery


@dataclasses.dataclass
class ConceptPreparedness:
    concept: Concept
    importance: int | None
    mastery: ConceptMasteryResult


@dataclasses.dataclass
class AssessmentPreparedness:
    assessment: Assessment
    concepts: list[ConceptPreparedness]

    def _by_level(self, level: MasteryLevel) -> list[ConceptPreparedness]:
        return [c for c in self.concepts if c.mastery.level == level]

    @property
    def strong(self) -> list[ConceptPreparedness]:
        return self._by_level(MasteryLevel.STRONG)

    @property
    def developing(self) -> list[ConceptPreparedness]:
        return self._by_level(MasteryLevel.DEVELOPING)

    @property
    def weak(self) -> list[ConceptPreparedness]:
        return self._by_level(MasteryLevel.WEAK)

    @property
    def no_evidence(self) -> list[ConceptPreparedness]:
        return self._by_level(MasteryLevel.NO_EVIDENCE)

    @property
    def overall_score(self) -> float | None:
        """Importance-weighted average of concepts WITH evidence only.
        None if nothing linked has any evidence yet — that's a
        distinct, honest state, not a 0."""
        scored = [(c.importance or 1, c.mastery.score) for c in self.concepts if c.mastery.score is not None]
        if not scored:
            return None
        total_weight = sum(w for w, _ in scored)
        return sum(w * s for w, s in scored) / total_weight

    @property
    def coverage(self) -> float:
        """Fraction of the assessment's importance-weight that has ANY
        mastery evidence at all — deliberately separate from
        overall_score so a strong score on a small studied slice of
        the material isn't mistaken for full readiness."""
        if not self.concepts:
            return 0.0
        total_weight = sum(c.importance or 1 for c in self.concepts)
        covered_weight = sum((c.importance or 1) for c in self.concepts if c.mastery.level != MasteryLevel.NO_EVIDENCE)
        return covered_weight / total_weight if total_weight else 0.0


def compute_assessment_preparedness(
    session: Session, assessment_id: int, *, as_of: datetime.datetime | None = None
) -> AssessmentPreparedness:
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise LookupError(f"No assessment with id {assessment_id}")

    links = list(
        session.execute(select(AssessmentConcept).where(AssessmentConcept.assessment_id == assessment_id)).scalars()
    )

    concept_preparedness = [
        ConceptPreparedness(
            concept=link.concept,
            importance=link.importance,
            mastery=compute_concept_mastery(session, link.concept_id, as_of=as_of),
        )
        for link in links
    ]

    return AssessmentPreparedness(assessment=assessment, concepts=concept_preparedness)
