"""Who a chat is about, and how they are named to the model (CLAUDE.md Principle 2).

The model never sees a family member's display name. In a member chat the person is
"the patient"; in a family chat each member is a label ("Member A", "Member B", ...) assigned
in the order members were added, never by name. Names typed by the user are replaced by these
labels before anything is sent, labels in the model's reply are mapped back to names only on
our backend, and a final check refuses to send anything that still contains a name.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.models import Patient

PATIENT_LABEL = "the patient"
AMBIGUOUS_NAME = "a family member"
FAMILY_PHRASE = "the family"
# Words in a family's name that say nothing about who it is ("Sharma family", "Mum's side").
_FAMILY_NAME_STOPWORDS = {"family", "families", "the", "and", "our", "side", "house", "home"}
MIN_NAME_PART = 3  # shorter name parts are only replaced as part of the full name
# Words our own labels use; a name made of them cannot be told apart from a label.
_LABEL_WORDS = {"the", "patient", "member", "family", "a"}


class PrivacyGuardError(Exception):
    """A display name was about to be sent to the model. Nothing was sent."""


@dataclass(frozen=True)
class ScopedMember:
    label: str
    id: uuid.UUID
    display_name: str
    sex: str
    date_of_birth: date | None

    def age_on(self, today: date) -> int | None:
        if self.date_of_birth is None:
            return None
        birth = self.date_of_birth
        return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _letters(index: int) -> str:
    """0 → "A", 25 → "Z", 26 → "AA", ..."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", text)


def _words_regex(phrase: str) -> str:
    """`phrase` as whole words, with any spacing between them."""
    words = [re.escape(word) for word in phrase.split()]
    return r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)"


def _pattern(phrase: str) -> re.Pattern[str]:
    """`phrase` as whole words, any case, any spacing between its words."""
    return re.compile(_words_regex(phrase), re.IGNORECASE)


class ChatScope:
    def __init__(
        self,
        kind: Literal["member", "family"],
        members: Sequence[ScopedMember],
        family_name: str | None = None,
    ) -> None:
        self.kind = kind
        self.members = tuple(members)
        self._by_label = {m.label.casefold(): m for m in self.members}

        # name or name part → replacement; full names first, then longer parts first.
        replacements: dict[str, str] = {}
        parts: dict[str, set[str]] = {}
        for member in self.members:
            if not set(map(str.casefold, _words(member.display_name))) <= _LABEL_WORDS:
                replacements[member.display_name.casefold()] = member.label
            for word in _words(member.display_name):
                if len(word) >= MIN_NAME_PART and word.casefold() not in _LABEL_WORDS:
                    parts.setdefault(word.casefold(), set()).add(member.label)
        for word, labels in parts.items():
            if word not in replacements:
                replacements[word] = labels.pop() if len(labels) == 1 else AMBIGUOUS_NAME
        # Members' names (and their parts) are what must never reach the model: the guard
        # checks exactly these. The family's name is also replaced, but not guarded: its words
        # can be ordinary ones ("Iron family") that appear in lab text.
        self._guarded = [_pattern(name) for name in replacements if name.strip()]
        if family_name:
            replacements.setdefault(family_name.casefold(), FAMILY_PHRASE)
            for word in _words(family_name):
                key = word.casefold()
                if len(word) >= MIN_NAME_PART and key not in _FAMILY_NAME_STOPWORDS:
                    replacements.setdefault(key, FAMILY_PHRASE)
        ordered = sorted(replacements.items(), key=lambda item: -len(item[0]))
        self._outgoing = [(_pattern(name), label) for name, label in ordered if name.strip()]
        if family_name and family_name.strip():
            # "the Sharma family" → "the family", not "the the family".
            self._outgoing.insert(0, (_pattern("the " + family_name), FAMILY_PHRASE))
        self._incoming = [
            (_pattern(member.label), member.display_name)
            for member in sorted(self.members, key=lambda m: -len(m.label))
        ]

    @classmethod
    def for_member(cls, patient: Patient) -> "ChatScope":
        return cls("member", [_scoped(patient, PATIENT_LABEL)])

    @classmethod
    def for_family(cls, family_name: str, patients: Sequence[Patient]) -> "ChatScope":
        ordered = sorted(patients, key=lambda p: (p.created_at, str(p.id)))
        members = [_scoped(p, f"Member {_letters(i)}") for i, p in enumerate(ordered)]
        return cls("family", members, family_name)

    @property
    def patient_ids(self) -> list[uuid.UUID]:
        return [member.id for member in self.members]

    @property
    def labels(self) -> list[str]:
        return [member.label for member in self.members]

    def member(self, label: str) -> ScopedMember | None:
        return self._by_label.get(" ".join(label.split()).casefold())

    def label_of(self, patient_id: uuid.UUID) -> str:
        return next(m.label for m in self.members if m.id == patient_id)

    def pseudonymize(self, text: str) -> str:
        """Replace members' names (and the family's name) with their labels."""
        for pattern, label in self._outgoing:
            text = pattern.sub(label, text)
        return text

    def depseudonymize(self, text: str) -> str:
        """Replace labels in the model's reply with members' display names (for the user)."""
        for pattern, name in self._incoming:
            text = pattern.sub(name, text)
        return text

    def names_in(self, text: str) -> list[str]:
        """Members' names (or name parts) still present in `text`. Used to fail closed."""
        return [pattern.pattern for pattern in self._guarded if pattern.search(text)]

    def check_outgoing(self, texts: Sequence[str]) -> None:
        for text in texts:
            if self.names_in(text):
                # Never include the name or the text: this message may be logged.
                raise PrivacyGuardError("A family member's name was about to reach the model.")


def _scoped(patient: Patient, label: str) -> ScopedMember:
    return ScopedMember(
        label=label,
        id=patient.id,
        display_name=patient.display_name,
        sex=patient.sex,
        date_of_birth=patient.date_of_birth,
    )
