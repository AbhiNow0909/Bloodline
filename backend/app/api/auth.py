from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.schemas.auth import LoginRequest, TokenResponse, UserRead
from app.security import create_access_token
from app.services.users import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid email or password"}},
)
def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    user = authenticate(db, body.email, body.password)
    if user is None:
        # Same response for unknown email and wrong password.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = user.id
    db.commit()  # persists an upgraded password hash, if authenticate() produced one
    return TokenResponse(
        access_token=create_access_token(user_id),
        expires_in=get_settings().jwt_expire_minutes * 60,
    )


@router.get("/me")
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
