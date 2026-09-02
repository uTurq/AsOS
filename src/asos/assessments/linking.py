"""Linking concepts and documents to assessments — what an assessment
actually covers. Idempotent: calling twice with a different importance
updates it rather than creating a duplicate link."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.db.models import AssessmentConcept, AssessmentDocument


def link_concept(
    session: Session, *, assessment_id: int, concept_id: int, importance: int | None = None
) -> AssessmentConcept:
    existing = session.execute(
        select(AssessmentConcept).where(
            AssessmentConcept.assessment_id == assessment_id, AssessmentConcept.concept_id == concept_id
        )
    ).scalar_one_or_none()
    if existing:
        existing.importance = importance
        session.commit()
        return existing

    link = AssessmentConcept(assessment_id=assessment_id, concept_id=concept_id, importance=importance)
    session.add(link)
    session.commit()
    return link


def link_document(session: Session, *, assessment_id: int, document_id: int) -> AssessmentDocument:
    existing = session.execute(
        select(AssessmentDocument).where(
            AssessmentDocument.assessment_id == assessment_id, AssessmentDocument.document_id == document_id
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    link = AssessmentDocument(assessment_id=assessment_id, document_id=document_id)
    session.add(link)
    session.commit()
    return link
