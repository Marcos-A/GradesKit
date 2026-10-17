"""Match Moodle participants with the students of the teacher's grades sheet.

Moodle writes "Nom Cognoms" ("Sara Noemi Alban Argandoña") while teacher
sheets usually use "Cognoms, Nom" ("Alban Argandoña, Sara Noemi"), often with
accents typed differently. Names are therefore compared as normalised words.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from gradeskit.tabular import strip_accents

STATUS_EXACT = "exact"
STATUS_PROBABLE = "probable"
STATUS_NONE = "none"

SCORE_EMAIL = 4
SCORE_SAME_WORDS = 3
SCORE_SUBSET = 2
SCORE_SIMILAR = 1
SIMILARITY_THRESHOLD = 0.88
NON_WORD_PATTERN = re.compile(r"[^\w]+", re.UNICODE)


@dataclass
class Person:
    key: int
    name: str
    email: str = ""


@dataclass
class Match:
    status: str
    candidate: int | None = None
    score: int = 0
    alternatives: list[int] = field(default_factory=list)


def name_words(name: str) -> list[str]:
    """Normalised words of a name, reordering "Cognoms, Nom" to "Nom Cognoms"."""

    if "," in name:
        surname, first_name = name.split(",", 1)
        name = f"{first_name} {surname}"
    cleaned = NON_WORD_PATTERN.sub(" ", strip_accents(name).casefold())
    return cleaned.split()


def match_score(left: Person, right: Person) -> int:
    if left.email and right.email and left.email.casefold() == right.email.casefold():
        return SCORE_EMAIL

    left_words, right_words = name_words(left.name), name_words(right.name)
    if not left_words or not right_words:
        return 0
    if sorted(left_words) == sorted(right_words):
        return SCORE_SAME_WORDS

    shorter, longer = sorted((set(left_words), set(right_words)), key=len)
    # A missing second surname or middle name: every word of the shorter
    # name appears in the longer one.
    if len(shorter) >= 2 and shorter <= longer:
        return SCORE_SUBSET

    # Typos such as "Jodar" / "Jordar".
    ratio = SequenceMatcher(None, " ".join(left_words), " ".join(right_words)).ratio()
    if ratio >= SIMILARITY_THRESHOLD:
        return SCORE_SIMILAR
    return 0


def match_people(participants: list[Person], students: list[Person]) -> dict[int, Match]:
    """Pair each participant with at most one student.

    Strongest pairs are assigned first. A participant with two equally good
    candidates is left unmatched, so the teacher picks the right one.
    """

    scores = {
        (participant.key, student.key): score
        for participant in participants
        for student in students
        if (score := match_score(participant, student)) > 0
    }

    best_for_participant: dict[int, list[int]] = {}
    for participant in participants:
        candidates = [(score, student) for (p_key, student), score in scores.items() if p_key == participant.key]
        if candidates:
            top = max(score for score, _ in candidates)
            best_for_participant[participant.key] = [student for score, student in candidates if score == top]

    matches = {participant.key: Match(status=STATUS_NONE) for participant in participants}
    used_students: set[int] = set()
    for (participant_key, student_key), score in sorted(scores.items(), key=lambda item: -item[1]):
        match = matches[participant_key]
        if match.candidate is not None or student_key in used_students:
            continue
        best = best_for_participant[participant_key]
        if len(best) > 1:
            match.alternatives = best
            continue
        if student_key not in best:
            continue
        match.candidate = student_key
        match.score = score
        match.status = STATUS_EXACT if score >= SCORE_SAME_WORDS else STATUS_PROBABLE
        used_students.add(student_key)
    return matches
