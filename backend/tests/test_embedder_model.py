"""The real embedding model (fastembed + BAAI/bge-small-en-v1.5).

The model tests run only where the model is already downloaded (EMBEDDING_CACHE_DIR, by
default ~/.cache/fastembed); they never download it. CI's backend job skips them, and the CI
Docker job checks the model baked into the image instead. The other tests here need no model.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.embeddings import (
    EmbeddingError,
    FastEmbedder,
    chunk_report,
    index_report,
    search_report_text,
)
from tests.embedding_helpers import add_confirmed_report, synthetic_extraction
from tests.factories import add_patient


@pytest.fixture(scope="module")
def model() -> FastEmbedder:
    settings = get_settings()
    embedder = FastEmbedder(
        settings.embedding_model, str(settings.embedding_cache_dir), offline=True, threads=1
    )
    try:
        embedder.embed_query("warm up")
    except EmbeddingError:
        pytest.skip("the embedding model is not downloaded (offline)")
    return embedder


@pytest.mark.model
def test_vectors_have_the_database_size_and_unit_length(model: FastEmbedder) -> None:
    passages = model.embed_passages(["Ferritin 48.3 ng/mL", "Creatinine 84.2 mg/dL"])
    query = model.embed_query("ferritin")

    assert [len(v) for v in [*passages, query]] == [384, 384, 384]
    for vector in [*passages, query]:
        assert sum(x * x for x in vector) == pytest.approx(1.0, abs=1e-3)
    assert model.embed_query("ferritin") == query  # deterministic
    assert model.embed_passages([]) == []


@pytest.mark.model
@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("how was ferritin measured", "Chemi Luminescent Microparticle Immunoassay"),
        ("ferritin reference range for women", "Women: 4.63 - 204.00 ng/ml"),
        ("creatinine in urine", "CREATININE - URINE PHOTOMETRY 84.20 mg/dL"),
        ("urine albumin method", "URINARY MICROALBUMIN PHOTOMETRY 12.6"),
    ],
)
def test_questions_find_the_right_page_of_the_synthetic_report(
    model: FastEmbedder, db_session: Session, question: str, expected: str
) -> None:
    patient = add_patient(db_session)
    report = add_confirmed_report(db_session, patient)
    index_report(db_session, report, model)

    best = search_report_text(db_session, model, [patient.id], question, k=1)[0]
    assert expected in best.content


@pytest.mark.model
def test_the_ferritin_page_ranks_first_for_iron_questions(model: FastEmbedder) -> None:
    chunks = chunk_report(synthetic_extraction().pages)
    vectors = model.embed_passages(chunks)
    query = model.embed_query("iron stores")
    scores = [sum(a * b for a, b in zip(v, query, strict=True)) for v in vectors]
    assert max(range(len(chunks)), key=scores.__getitem__) == 2  # the SERUM ferritin page


def test_a_missing_model_is_a_clear_error_and_never_downloads(tmp_path: Path) -> None:
    embedder = FastEmbedder("BAAI/bge-small-en-v1.5", str(tmp_path), offline=True, threads=1)
    with pytest.raises(EmbeddingError, match="could not be loaded"):
        embedder.embed_query("ferritin")
    assert not any(tmp_path.rglob("*.onnx"))


def test_a_model_of_the_wrong_size_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class WideModel:
        embedding_size = 768

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr("fastembed.TextEmbedding", WideModel)
    embedder = FastEmbedder("some/768-dim-model", "/nonexistent", offline=True, threads=1)
    with pytest.raises(EmbeddingError, match="768-dimensional"):
        embedder.embed_query("ferritin")
