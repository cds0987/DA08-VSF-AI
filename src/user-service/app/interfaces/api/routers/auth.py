from fastapi import APIRouter, Depends, HTTPException, Request, status
from json import JSONDecodeError

from app.application.exceptions import (
    AccountLockedError,
    AuthenticationError,
    InactiveUserError,
    InvalidTokenError,
)
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.domain.entities.user import User
from app.interfaces.api.dependencies import (
    get_current_user,
    get_login_use_case,
    get_refresh_token_use_case,
)
from app.interfaces.api.schemas.auth import MeResponse, RefreshTokenRequest, TokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    use_case: LoginUseCase = Depends(get_login_use_case),
) -> TokenResponse:
    payload = await _read_login_payload(request)
    try:
        result = await use_case.execute(
            email=payload["email"],
            password=payload["password"],
            ip_address=request.client.host if request.client else None,
        )
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account locked. Try again after 15 minutes.",
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        ) from exc

    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
    )


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        role=_role_value(current_user.role),
        department=current_user.department,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshTokenRequest,
    use_case: RefreshTokenUseCase = Depends(get_refresh_token_use_case),
) -> TokenResponse:
    try:
        result = await use_case.execute(payload.refresh_token)
    except (InactiveUserError, InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
    )


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)


async def _read_login_payload(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="username and password are required",
            )
        return {"email": username, "password": password}

    try:
        body = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Malformed JSON body",
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="JSON body must be an object",
        )
    email = str(body.get("email", "")).strip()
    password = str(body.get("password", ""))
    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email and password are required",
        )
    return {"email": email, "password": password}
