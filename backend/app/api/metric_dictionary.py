from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import CanonicalMetric
from app.schemas.report import MetricDefinitionRead

router = APIRouter(prefix="/metric-dictionary", tags=["metric dictionary"])


@router.get("")
def list_metric_definitions(_: CurrentUser, db: DbSession) -> list[MetricDefinitionRead]:
    """Every biomarker the app knows, for mapping unknown test names during review."""
    definitions = db.scalars(
        select(CanonicalMetric).order_by(CanonicalMetric.category, CanonicalMetric.canonical_name)
    )
    return [MetricDefinitionRead.model_validate(definition) for definition in definitions]
