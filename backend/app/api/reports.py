"""Report upload, processing status, review, confirm, retry, file and delete.

Uploads are the raw PDF as the request body (`Content-Type: application/pdf`), not multipart:
authentication and family ownership are checked before a byte is read, and the size limit is
enforced while streaming. Every `{report_id}` route resolves the report through
`get_owned_report`.
"""

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    ClientFactoryDep,
    DbSession,
    OwnedPatient,
    OwnedReport,
    SessionFactoryDep,
)
from app.config import get_settings
from app.models import Report, ReportFile
from app.schemas.report import ConfirmReport, DuplicateReport, ReportRead, ReportReview
from app.services.ingestion import (
    ConfirmError,
    ReportStateError,
    StoredProcessing,
    confirm_report,
    process_report,
)

router = APIRouter(tags=["reports"])

_PDF_MAGIC = b"%PDF-"


def get_max_upload_bytes() -> int:
    return get_settings().max_upload_mb * 1024 * 1024


def _too_large(limit: int) -> HTTPException:
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"The file is larger than {limit // (1024 * 1024)} MB.",
    )


async def read_pdf_body(
    request: Request,
    patient: OwnedPatient,  # access is checked before the body is read
    limit: Annotated[int, Depends(get_max_upload_bytes)],
) -> bytes:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Send the PDF as the request body with Content-Type: application/pdf.",
        )
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _too_large(limit)

    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _too_large(limit)
        chunks.append(chunk)
    body = b"".join(chunks)

    if not body:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty.")
    if _PDF_MAGIC not in body[:1024]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is not a PDF.")
    return body


def _duplicate(report_id: object) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "message": "This report was already uploaded for this family member.",
            "report_id": str(report_id),
        },
    )


@router.post(
    "/patients/{patient_id}/reports",
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
    responses={
        status.HTTP_409_CONFLICT: {"model": DuplicateReport, "description": "Already uploaded"},
        status.HTTP_413_CONTENT_TOO_LARGE: {"description": "File too large"},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"description": "Not sent as application/pdf"},
    },
)
def upload_report(
    patient: OwnedPatient,
    pdf: Annotated[bytes, Depends(read_pdf_body)],
    db: DbSession,
    background: BackgroundTasks,
    session_factory: SessionFactoryDep,
    client_factory: ClientFactoryDep,
) -> ReportRead:
    """Upload a lab-report PDF for a family member. It is processed in the background; poll
    `GET /reports/{report_id}` until the status is `pending_review` (or `failed`)."""
    sha256 = hashlib.sha256(pdf).hexdigest()
    existing = db.scalar(
        select(Report.id).where(Report.patient_id == patient.id, Report.file_sha256 == sha256)
    )
    if existing is not None:
        raise _duplicate(existing)

    report = Report(patient_id=patient.id, file_sha256=sha256, status="processing")
    db.add(report)
    try:
        db.flush()
        db.add(ReportFile(report_id=report.id, content=pdf))
        db.commit()
    except IntegrityError:  # the same file uploaded twice at once
        db.rollback()
        raise _duplicate(
            db.scalar(
                select(Report.id).where(
                    Report.patient_id == patient.id, Report.file_sha256 == sha256
                )
            )
        ) from None

    background.add_task(
        process_report,
        report.id,
        session_factory=session_factory,
        client_factory=client_factory,
        model=get_settings().structuring_model,
    )
    return ReportRead.model_validate(report)


@router.get("/reports/{report_id}")
def get_report(report: OwnedReport) -> ReportRead:
    """Status and summary; poll this after uploading."""
    return ReportRead.model_validate(report)


@router.get("/reports/{report_id}/review", responses={status.HTTP_409_CONFLICT: {}})
def review_report(report: OwnedReport) -> ReportReview:
    """Extracted rows and warnings, to check against the original PDF before confirming."""
    if report.status != "pending_review" or report.raw_extraction is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"This report is not waiting for review (status: {report.status}).",
        )
    stored = StoredProcessing.model_validate(report.raw_extraction)
    return ReportReview(
        report=ReportRead.model_validate(report),
        printed_age_years=stored.extraction.printed_age_years,
        printed_sex=stored.extraction.printed_sex,
        sample_types=sorted({p.sample_type for p in stored.extraction.pages if p.sample_type}),
        warnings=stored.warnings,
        rows=list(stored.structured.metrics),
    )


@router.post(
    "/reports/{report_id}/confirm",
    responses={status.HTTP_409_CONFLICT: {}, status.HTTP_422_UNPROCESSABLE_CONTENT: {}},
)
def confirm(body: ConfirmReport, report: OwnedReport, db: DbSession) -> ReportRead:
    """Save the reviewed (and corrected) rows to the member's history."""
    try:
        confirm_report(db, report, body, now=datetime.now(UTC))
    except ReportStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ConfirmError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    db.commit()
    return ReportRead.model_validate(report)


@router.post(
    "/reports/{report_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_409_CONFLICT: {}},
)
def retry_report(
    report: OwnedReport,
    db: DbSession,
    background: BackgroundTasks,
    session_factory: SessionFactoryDep,
    client_factory: ClientFactoryDep,
) -> ReportRead:
    """Process a failed report again (e.g. after the AI service was busy)."""
    if report.status != "failed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Only failed reports can be retried ({report.status}).",
        )
    report.status = "processing"
    report.failure_reason = None
    db.commit()
    background.add_task(
        process_report,
        report.id,
        session_factory=session_factory,
        client_factory=client_factory,
        model=get_settings().structuring_model,
    )
    return ReportRead.model_validate(report)


@router.get(
    "/reports/{report_id}/file",
    response_class=Response,
    responses={status.HTTP_200_OK: {"content": {"application/pdf": {}}}},
)
def get_report_file(report: OwnedReport, db: DbSession) -> Response:
    """The original PDF, for viewing next to the extracted rows."""
    content = db.get_one(ReportFile, report.id).content
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="report.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report: OwnedReport, db: DbSession) -> Response:
    """Delete the report, its file and any metrics saved from it."""
    db.delete(report)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
