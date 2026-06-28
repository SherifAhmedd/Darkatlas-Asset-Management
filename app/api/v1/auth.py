from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.exceptions import ConflictException, UnauthorizedException
from app.models.user import User
from app.schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: UserRegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """
    Register a new user account.

    - A unique `tenant_id` UUID is automatically assigned to this user,
      representing their isolated organization namespace.
    - Returns a JWT access token immediately upon successful registration.
    """
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == payload.username))
    if result.scalar_one_or_none():
        raise ConflictException(
            message="Username already taken",
            detail={"username": payload.username}
        )

    # Create new user with a fresh tenant_id (one unique org namespace per user)
    new_user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        tenant_id=uuid.uuid4(),
    )
    db.add(new_user)

    try:
        await db.flush()  # Get the generated ID before commit
    except IntegrityError:
        await db.rollback()
        raise ConflictException(message="Username already taken")

    # Issue JWT token
    token = create_access_token(data={"sub": new_user.username})
    return TokenResponse(access_token=token)


from fastapi.security import OAuth2PasswordRequestForm


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive a JWT token",
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """
    Authenticate with username and password.

    Returns a JWT bearer token to use in the `Authorization` header
    for all protected endpoints.
    """
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    # Use the same error message for both missing user and wrong password
    # to prevent username enumeration attacks
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise UnauthorizedException(message="Invalid username or password")

    token = create_access_token(data={"sub": user.username})
    return TokenResponse(access_token=token)
