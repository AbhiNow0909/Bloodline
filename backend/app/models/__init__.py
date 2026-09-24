"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.metric import CanonicalMetric, Metric, MetricFlag
from app.models.patient import AccessRole, Patient, Sex, UserPatientAccess
from app.models.report import Report, ReportFile, ReportStatus
from app.models.report_chunk import EMBEDDING_DIMENSIONS, ReportChunk
from app.models.user import User

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AccessRole",
    "Base",
    "CanonicalMetric",
    "Metric",
    "MetricFlag",
    "Patient",
    "Report",
    "ReportChunk",
    "ReportFile",
    "ReportStatus",
    "Sex",
    "User",
    "UserPatientAccess",
]
