from typing import Annotated
import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.schemas.auth import CurrentUser

# OAuth2 scheme — tells Swagger UI to add the "Authorize" button
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    """
    Decode the JWT, look up the user by username, and return a CurrentUser context.
    Raises UnauthorizedException for any invalid/expired token.
    """
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if not username:
            raise UnauthorizedException("Token missing subject claim")
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Token has expired")
    except jwt.PyJWTError:
        raise UnauthorizedException("Invalid authentication token")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("User not found")

    return CurrentUser.model_validate(user)


# Convenience type alias — use this in route function signatures
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
