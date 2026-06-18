from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from json import JSONDecodeError

from app.application.exceptions import (
    AccountLockedError,
    AuthenticationError,
    InactiveUserError,
    InvalidTokenError,
)
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.logout_use_case import LogoutUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.core.config import get_settings
from app.domain.entities.user import User
from app.interfaces.api.dependencies import (
    get_current_user,
    get_login_use_case,
    get_logout_use_case,
    get_refresh_token_use_case,
)
from app.interfaces.api.schemas.auth import MeResponse, TokenResponse
from fastapi.param_functions import Form


router = APIRouter(prefix="/auth", tags=["auth"])

# Chat và admin chạy CÙNG host (chat ở "/", admin ở "/admin/") nên cookie host-only
# path="/" sẽ bị dùng CHUNG nếu cùng tên -> login/logout app này đè/xóa session app kia.
# Yêu cầu: hai app phải ĐỘC LẬP HOÀN TOÀN -> tách refresh token bằng TÊN cookie riêng.
# Path scope không tách được vì cả hai cùng gọi /api/user/auth/* nên phải tách bằng tên +
# endpoint admin riêng (FastAPI Cookie(alias=...) cố định theo từng endpoint).
_REFRESH_COOKIE = "refresh_token"  # chat (giữ nguyên — session chat hiện tại không bị phá)
_ADMIN_REFRESH_COOKIE = "eka.admin.refresh_token"  # admin
_REFRESH_COOKIE_MAX_AGE = get_settings().refresh_token_ttl_days * 24 * 3600


def _set_refresh_cookie(
    response: Response, token: str, cookie_name: str = _REFRESH_COOKIE
) -> None:
    settings = get_settings()
    response.set_cookie(
        key=cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path="/",
    )


def _clear_refresh_cookie(
    response: Response, cookie_name: str = _REFRESH_COOKIE
) -> None:
    settings = get_settings()
    response.set_cookie(
        key=cookie_name,
        value="",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=0,
        path="/",
    )


# Khai báo dependency giả lập trường để Swagger UI tự vẽ ô nhập liệu phẳng (username/password)
async def swagger_login_fields(
    username: str = Form(default="admin@company.com", description="Email đăng nhập"),
    password: str = Form(default="DemoAdminPassword123!", description="Mật khẩu")
):
    return None


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    _swagger_ui: None = Depends(swagger_login_fields),
    use_case: LoginUseCase = Depends(get_login_use_case),
) -> TokenResponse:
    return await _login(request, response, use_case)


@router.post("/admin/login", response_model=TokenResponse)
async def admin_login(
    request: Request,
    response: Response,
    _swagger_ui: None = Depends(swagger_login_fields),
    use_case: LoginUseCase = Depends(get_login_use_case),
) -> TokenResponse:
    # Admin dùng cookie refresh RIÊNG để độc lập hoàn toàn với chat (xem _ADMIN_REFRESH_COOKIE).
    return await _login(
        request, response, use_case,
        required_role="admin",
        cookie_name=_ADMIN_REFRESH_COOKIE,
    )


async def _login(
    request: Request,
    response: Response,
    use_case: LoginUseCase,
    required_role: str | None = None,
    cookie_name: str = _REFRESH_COOKIE,
) -> TokenResponse:
    payload = await _read_login_payload(request)
    try:
        result = await use_case.execute(
            email=payload["email"],
            password=payload["password"],
            ip_address=request.client.host if request.client else None,
            required_role=required_role,
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

    _set_refresh_cookie(response, result.refresh_token, cookie_name)
    return TokenResponse(access_token=result.access_token, token_type=result.token_type)


async def _logout(
    response: Response,
    refresh_token: str | None,
    use_case: LogoutUseCase,
    cookie_name: str,
) -> None:
    if refresh_token:
        try:
            await use_case.execute(refresh_token)
        except InvalidTokenError:
            pass  # Idempotent — already revoked or invalid tokens are fine
    _clear_refresh_cookie(response, cookie_name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    use_case: LogoutUseCase = Depends(get_logout_use_case),
) -> None:
    await _logout(response, refresh_token, use_case, _REFRESH_COOKIE)


@router.post("/admin/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_ADMIN_REFRESH_COOKIE),
    use_case: LogoutUseCase = Depends(get_logout_use_case),
) -> None:
    await _logout(response, refresh_token, use_case, _ADMIN_REFRESH_COOKIE)


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        role=_role_value(current_user.role),
        account_type=current_user.account_type,
    )


async def _refresh(
    response: Response,
    refresh_token: str | None,
    use_case: RefreshTokenUseCase,
    cookie_name: str,
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )
    try:
        result = await use_case.execute(refresh_token)
    except (InactiveUserError, InvalidTokenError) as exc:
        _clear_refresh_cookie(response, cookie_name)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc

    _set_refresh_cookie(response, result.refresh_token, cookie_name)
    return TokenResponse(access_token=result.access_token, token_type=result.token_type)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    use_case: RefreshTokenUseCase = Depends(get_refresh_token_use_case),
) -> TokenResponse:
    return await _refresh(response, refresh_token, use_case, _REFRESH_COOKIE)


@router.post("/admin/refresh", response_model=TokenResponse)
async def admin_refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_ADMIN_REFRESH_COOKIE),
    use_case: RefreshTokenUseCase = Depends(get_refresh_token_use_case),
) -> TokenResponse:
    return await _refresh(response, refresh_token, use_case, _ADMIN_REFRESH_COOKIE)


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
