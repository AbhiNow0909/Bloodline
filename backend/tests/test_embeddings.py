"""Indexing confirmed reports and searching their text, always within given members.

Real Postgres + pgvector; the embedding model is the deterministic FakeEmbedder (the real
model is exercised in test_embedder_model.py and in the CI image smoke test).
"""

import logging
import uuid
from contextlib import nullcontext

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Patient, Report, ReportChunk
from app.services.embeddings import (
    NotIndexableError,
    index_report,
    index_report_task,
    reports_to_index,
    search_report_text,
)
from app.services.embeddings.search import MAX_K
from tests.embedding_helpers import (
    BrokenEmbedder,
    FakeEmbedder,
    add_confirmed_report,
    extraction_with_pages,
)
from tests.factories import add, add_family, add_patient, build_chunk, build_report


def _chunks(session: Session, report: Report) -> list[ReportChunk]:
    return list(
        session.scalars(
            select(ReportChunk)
            .where(ReportChunk.report_id == report.id)
            .order_by(ReportChunk.chunk_index)
        )
    )


def _indexed(session: Session, patient: Patient, *texts: str) -> Report:
    report = add_confirmed_report(session, patient, extraction_with_pages(*texts))
    index_report(session, report, FakeEmbedder())
    return report


# --- indexing ---------------------------------------------------------------------------------


def test_a_confirmed_report_is_indexed_from_its_scrubbed_text(db_session: Session) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(db_session, patient)
    embedder = FakeEmbedder()

    assert index_report(db_session, report, embedder) == 3

    chunks = _chunks(db_session, report)
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.patient_id == patient.id for c in chunks)
    assert [c.content for c in chunks] == embedder.passages
    assert chunks[2].content.startswith("Sample type: SERUM\n")
    assert len(chunks[0].embedding) == 384


def test_reindexing_replaces_the_chunks(db_session: Session) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(db_session, patient)
    index_report(db_session, report, FakeEmbedder())
    first = {c.id for c in _chunks(db_session, report)}

    assert index_report(db_session, report, FakeEmbedder()) == 3
    chunks = _chunks(db_session, report)
    assert len(chunks) == 3
    assert first.isdisjoint(c.id for c in chunks)


def test_a_failing_model_keeps_the_existing_chunks(db_session: Session) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(db_session, patient)
    index_report(db_session, report, FakeEmbedder())

    with pytest.raises(RuntimeError):
        index_report(db_session, report, BrokenEmbedder())
    assert len(_chunks(db_session, report)) == 3


@pytest.mark.parametrize("status", ["processing", "pending_review", "failed"])
def test_only_confirmed_reports_are_indexed(db_session: Session, status: str) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(db_session, patient, status=status)
    with pytest.raises(NotIndexableError):
        index_report(db_session, report, FakeEmbedder())


def test_the_background_task_indexes_and_logs_failures_without_text(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(db_session, patient)
    db_session.commit()  # confirmed before the task runs; its rollback must not undo that
    factory = lambda: nullcontext(db_session)  # noqa: E731

    with caplog.at_level(logging.INFO):
        index_report_task(report.id, session_factory=factory, embedder_factory=BrokenEmbedder)
    assert _chunks(db_session, report) == []
    assert f"Could not index report {report.id} (RuntimeError)" in caplog.text
    assert "FERRITIN" not in caplog.text
    assert "Sample type" not in caplog.text

    index_report_task(report.id, session_factory=factory, embedder_factory=FakeEmbedder)
    assert len(_chunks(db_session, report)) == 3

    # A report deleted before its task runs is skipped quietly.
    index_report_task(uuid.uuid4(), session_factory=factory, embedder_factory=FakeEmbedder)


def test_reports_to_index_lists_confirmed_reports_without_chunks(db_session: Session) -> None:
    patient = add_patient(db_session)
    done = add_confirmed_report(db_session, patient)
    index_report(db_session, done, FakeEmbedder())
    waiting = add_confirmed_report(db_session, patient)
    add(db_session, build_report(patient, status="pending_review"))

    assert reports_to_index(db_session) == [waiting.id]
    assert set(reports_to_index(db_session, include_indexed=True)) == {done.id, waiting.id}


def test_deleting_a_report_deletes_its_chunks(db_session: Session) -> None:
    patient = add_patient(db_session)
    report = _indexed(db_session, patient, "Ferritin method CMIA")
    db_session.delete(report)
    db_session.flush()
    assert db_session.scalars(select(ReportChunk)).all() == []


# --- search -----------------------------------------------------------------------------------


def test_search_finds_the_closest_text_with_its_report(db_session: Session) -> None:
    patient = add_patient(db_session)
    report = _indexed(
        db_session,
        patient,
        "FERRITIN 48.3 ng/mL Method : Chemi Luminescent Immunoassay",
        "CREATININE URINE 84.20 mg/dL Method : Jaffe",
    )

    hits = search_report_text(db_session, FakeEmbedder(), [patient.id], "ferritin method", k=2)

    assert [h.chunk_index for h in hits] == [0, 1]
    assert hits[0].score > hits[1].score
    assert hits[0].content.startswith("Sample type: SERUM\nFERRITIN")
    assert hits[0].report_id == report.id
    assert hits[0].patient_id == patient.id
    assert hits[0].lab_name == "Example Labs"
    assert hits[0].collected_at == report.collected_at


def test_a_search_for_one_member_never_returns_another_members_text(db_session: Session) -> None:
    family = add_family(db_session)
    member_a = add_patient(db_session, family)
    member_b = add_patient(db_session, family)
    _indexed(db_session, member_a, "Urine creatinine Jaffe method")
    # B's text matches the query word for word; A's barely does.
    _indexed(db_session, member_b, "Ferritin chemi luminescent immunoassay method")

    hits = search_report_text(
        db_session, FakeEmbedder(), [member_a.id], "ferritin chemi luminescent immunoassay", k=20
    )
    assert hits
    assert {h.patient_id for h in hits} == {member_a.id}


def test_a_family_search_never_reaches_another_family(db_session: Session) -> None:
    ours = add_family(db_session)
    theirs = add_family(db_session)
    mum = add_patient(db_session, ours)
    dad = add_patient(db_session, ours)
    stranger = add_patient(db_session, theirs)
    _indexed(db_session, mum, "Ferritin method immunoassay")
    _indexed(db_session, dad, "Ferritin reference interval men")
    _indexed(db_session, stranger, "Ferritin method immunoassay reference interval men")

    family_ids = [mum.id, dad.id]
    hits = search_report_text(db_session, FakeEmbedder(), family_ids, "ferritin", k=20)
    assert {h.patient_id for h in hits} == {mum.id, dad.id}


def test_no_members_or_no_query_means_no_results_and_no_model_call(db_session: Session) -> None:
    patient = add_patient(db_session)
    _indexed(db_session, patient, "Ferritin method")
    embedder = FakeEmbedder()

    assert search_report_text(db_session, embedder, [], "ferritin") == []
    assert search_report_text(db_session, embedder, [patient.id], "   ") == []
    assert embedder.queries == []


def test_k_is_kept_within_limits_and_the_query_is_trimmed(db_session: Session) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(
        db_session, patient, extraction_with_pages(*[f"Note {n}" for n in range(25)])
    )
    index_report(db_session, report, FakeEmbedder())
    embedder = FakeEmbedder()

    assert len(search_report_text(db_session, embedder, [patient.id], "note", k=0)) == 1
    assert len(search_report_text(db_session, embedder, [patient.id], "note", k=500)) == MAX_K
    search_report_text(db_session, embedder, [patient.id], "  ferritin \n  method  " + "x" * 600)
    assert embedder.queries[-1].startswith("ferritin method x")
    assert len(embedder.queries[-1]) == 500


def test_a_filtered_search_through_the_hnsw_index_still_returns_every_match(
    db_session: Session,
) -> None:
    """With a WHERE filter, a plain HNSW scan only looks at ef_search candidates and can
    return fewer rows than asked for. Our search turns on pgvector's iterative scan."""
    family = add_family(db_session)
    ours = add_patient(db_session, family)
    others = add_patient(db_session, family)
    _indexed(db_session, ours, "Urine creatinine Jaffe", "Microalbumin turbidimetry", "Note")
    crowd = add(db_session, build_report(others, status="confirmed"))
    embedder = FakeEmbedder()
    db_session.add_all(
        build_chunk(crowd, chunk_index=n, content=f"Ferritin {n}", embedding=e)
        for n, e in enumerate(embedder.embed_passages([f"ferritin {n}" for n in range(200)]))
    )
    db_session.flush()
    db_session.execute(text("ANALYZE report_chunks"))
    # Force the planner onto the HNSW index. (At family scale it usually picks the exact
    # patient_id index instead; this is the path for larger tables.) Rolled back after the test.
    db_session.execute(text("DROP INDEX ix_report_chunks_patient_id"))
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    db_session.execute(text("SET LOCAL enable_bitmapscan = off"))
    db_session.execute(text("SET LOCAL hnsw.ef_search = 10"))

    query = embedder.embed_query("ferritin")
    db_session.execute(text("SET LOCAL hnsw.iterative_scan = off"))
    plain = db_session.execute(
        text(
            "SELECT id FROM report_chunks WHERE patient_id = :pid"
            " ORDER BY embedding <=> CAST(:q AS vector) LIMIT 5"
        ),
        {"pid": ours.id, "q": str(query)},
    ).all()
    assert len(plain) < 3  # the problem: the index stops before reaching our chunks

    hits = search_report_text(db_session, embedder, [ours.id], "ferritin", k=5)
    assert len(hits) == 3
    assert {h.patient_id for h in hits} == {ours.id}
    plan = "\n".join(
        row[0]
        for row in db_session.execute(
            text(
                "EXPLAIN SELECT id FROM report_chunks WHERE patient_id = :pid"
                " ORDER BY embedding <=> CAST(:q AS vector) LIMIT 5"
            ),
            {"pid": ours.id, "q": str(query)},
        )
    )
    assert "ix_report_chunks_embedding_hnsw" in plan
