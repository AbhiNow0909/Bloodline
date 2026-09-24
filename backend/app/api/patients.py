"""Family members ("patients"). Every `{patient_id}` route resolves access via
`get_patient_access`; changing or deleting a patient requires the owner role."""

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OwnerAccess, PatientAccessDep
from app.models import Patient, UserPatientAccess
from app.schemas.patient import PatientCreate, PatientRead, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("")
def list_patients(user: CurrentUser, db: DbSession) -> list[PatientRead]:
    """Patients the current user can access, with their role for each."""
    rows = db.execute(
        select(Patient, UserPatientAccess.role)
        .join(UserPatientAccess, UserPatientAccess.patient_id == Patient.id)
        .where(UserPatientAccess.user_id == user.id)
        .order_by(Patient.display_name, Patient.created_at)
    ).tuples()
    return [PatientRead.from_model(patient, role) for patient, role in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_patient(body: PatientCreate, user: CurrentUser, db: DbSession) -> PatientRead:
    """Create a patient; the creator becomes its owner."""
    patient = Patient(**body.model_dump())
    db.add(patient)
    db.flush()
    db.add(UserPatientAccess(user_id=user.id, patient_id=patient.id, role="owner"))
    db.commit()
    return PatientRead.from_model(patient, "owner")


@router.get("/{patient_id}")
def get_patient(access: PatientAccessDep) -> PatientRead:
    return PatientRead.from_model(access.patient, access.role)


@router.patch("/{patient_id}")
def update_patient(body: PatientUpdate, access: OwnerAccess, db: DbSession) -> PatientRead:
    patient = access.patient
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    db.commit()
    return PatientRead.from_model(patient, access.role)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patient(access: OwnerAccess, db: DbSession) -> Response:
    """Delete the patient and, by cascade, all their reports, metrics and files."""
    db.delete(access.patient)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
