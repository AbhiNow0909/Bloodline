"""A single family member ("patient"). Members are listed and created under their family
(`/families/{family_id}/patients`); every `{patient_id}` route resolves the member through
`get_owned_patient`, so only the owner of the member's family can reach it."""

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession, OwnedPatient
from app.schemas.patient import PatientRead, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/{patient_id}")
def get_patient(patient: OwnedPatient) -> PatientRead:
    return PatientRead.model_validate(patient)


@router.patch("/{patient_id}")
def update_patient(body: PatientUpdate, patient: OwnedPatient, db: DbSession) -> PatientRead:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    db.commit()
    return PatientRead.model_validate(patient)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patient(patient: OwnedPatient, db: DbSession) -> Response:
    """Delete the member and, by cascade, all their reports, metrics and files."""
    db.delete(patient)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
