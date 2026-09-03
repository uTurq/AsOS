from __future__ import annotations

from asos.db.models import Concept, Course
from asos.memory.episodic import record_episodic_note


def test_record_episodic_note(session):
    note = record_episodic_note(session, content="Still confused about light reactions despite 3 reviews.")
    assert note.id is not None
    assert note.content == "Still confused about light reactions despite 3 reviews."


def test_record_episodic_note_scoped_to_course_and_concept(session):
    course = Course(name="Biology 101")
    session.add(course)
    session.commit()
    concept = Concept(course_id=course.id, name="Photosynthesis")
    session.add(concept)
    session.commit()

    note = record_episodic_note(
        session, content="Struggles with light reactions specifically.", course_id=course.id, concept_id=concept.id
    )
    assert note.course_id == course.id
    assert note.concept_id == concept.id
