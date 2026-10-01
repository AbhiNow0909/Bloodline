"""Labels instead of names: what the model may see, and mapping back for the user."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.models import Patient
from app.services.agent import ChatScope, PrivacyGuardError
from app.services.agent.scope import _letters


def patient(name: str, sex: str = "female", *, added: int = 0, born: date | None = None) -> Patient:
    return Patient(
        id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        display_name=name,
        sex=sex,
        date_of_birth=born,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=added),
    )


def test_labels_follow_the_order_members_were_added_not_their_names() -> None:
    scope = ChatScope.for_family(
        "Rao family", [patient("Zara", added=2), patient("Amma", added=0), patient("Ravi", added=1)]
    )
    assert [(m.label, m.display_name) for m in scope.members] == [
        ("Member A", "Amma"),
        ("Member B", "Ravi"),
        ("Member C", "Zara"),
    ]
    assert [_letters(i) for i in (0, 25, 26, 27, 51, 52)] == ["A", "Z", "AA", "AB", "AZ", "BA"]


def test_member_chat_calls_the_person_the_patient() -> None:
    scope = ChatScope.for_member(patient("Asha Rao"))
    assert scope.pseudonymize("What is Asha's ferritin? Has asha rao's HbA1c changed?") == (
        "What is the patient's ferritin? Has the patient's HbA1c changed?"
    )
    assert scope.depseudonymize("The patient's ferritin was 48.3 ng/mL.") == (
        "Asha Rao's ferritin was 48.3 ng/mL."
    )


def test_family_chat_replaces_names_any_case_and_spacing() -> None:
    scope = ChatScope.for_family(
        "Sharma family", [patient("Amma"), patient("Ravi Kumar", "male", added=1)]
    )
    assert scope.pseudonymize("Compare AMMA and ravi   kumar. Is Ravi's LDL high?") == (
        "Compare Member A and Member B. Is Member B's LDL high?"
    )
    # Only whole words: "Ravioli" is not Ravi.
    assert scope.pseudonymize("Ravioli for dinner") == "Ravioli for dinner"


def test_a_shared_surname_is_replaced_without_pointing_at_anyone() -> None:
    scope = ChatScope.for_family(
        "Our family", [patient("Asha Rao"), patient("Vikram Rao", "male", added=1)]
    )
    assert scope.pseudonymize("How are the Raos? Is Rao's ferritin low?") == (
        "How are the Raos? Is a family member's ferritin low?"
    )
    assert scope.pseudonymize("And Asha?") == "And Member A?"


def test_the_family_name_is_not_sent_either() -> None:
    scope = ChatScope.for_family("Sharma family", [patient("Amma")])
    assert scope.pseudonymize("Who in the Sharma family has high LDL?") == (
        "Who in the family has high LDL?"
    )
    assert scope.pseudonymize("Is anyone in my family anaemic?") == (
        "Is anyone in my family anaemic?"
    )


def test_labels_in_the_reply_become_names_in_any_case() -> None:
    scope = ChatScope.for_family("F", [patient("Amma"), patient("Appa", "male", added=1)])
    reply = "Member A\u2019s ferritin is low; member b and MEMBER  A were tested on 3 Mar 2025."
    assert scope.depseudonymize(reply) == (
        "Amma\u2019s ferritin is low; Appa and Amma were tested on 3 Mar 2025."
    )


def test_labels_resolve_case_insensitively_and_unknown_labels_do_not() -> None:
    scope = ChatScope.for_family("F", [patient("Amma"), patient("Appa", "male", added=1)])
    assert scope.member("member  b") is not None
    assert scope.member("Member C") is None
    assert scope.member("Appa") is None  # names are not labels


def test_the_guard_refuses_text_that_still_contains_a_name() -> None:
    scope = ChatScope.for_family("F", [patient("Asha Rao")])
    scope.check_outgoing(["Member A's ferritin", '{"member": "Member A"}'])
    with pytest.raises(PrivacyGuardError) as raised:
        scope.check_outgoing(["fine", "Report for ASHA"])
    assert "asha" not in str(raised.value).casefold()


def test_names_made_of_label_words_do_not_break_labels() -> None:
    scope = ChatScope.for_member(patient("Patient"))
    scope.check_outgoing(["How is the patient?"])
    assert scope.pseudonymize("How is the patient?") == "How is the patient?"


def test_ages_come_from_date_of_birth() -> None:
    member = ChatScope.for_member(patient("Amma", born=date(1968, 3, 1))).members[0]
    assert member.age_on(date(2026, 2, 28)) == 57
    assert member.age_on(date(2026, 3, 1)) == 58
    assert ChatScope.for_member(patient("Appa")).members[0].age_on(date(2026, 3, 1)) is None


def test_the_guard_watches_member_names_not_family_name_words() -> None:
    scope = ChatScope.for_family("Iron family", [patient("Asha Rao")])
    scope.check_outgoing(["Ferritin reflects the body's iron stores."])  # lab text: fine
    with pytest.raises(PrivacyGuardError):
        scope.check_outgoing(["Rao"])
