from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.exceptions import (
    InactiveUserError,
    InvalidTokenError,
    PermissionDeniedError,
)
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.application.use_cases.auth.verify_token_use_case import VerifyTokenUseCase
from app.application.use_cases.users.list_users_use_case import ListUsersUseCase
from app.application.use_cases.users.set_user_active_use_case import SetUserActiveUseCase
from app.core.config import Settings, get_settings
from app.domain.entities.user import User
from app.infrastructure.db.postgres_audit_log_repository import PostgresAuditLogRepository
from app.infrastructure.db.postgres_refresh_token_repository import (
    PostgresRefreshTokenRepository,
)
from app.infrastructure.db.postgres_user_repository import (
    PostgresLoginStateRepository,
    PostgresUserRepository,
)
from app.infrastructure.db.session import get_session
from app.infrastructure.security.jwt_token_service import JwtTokenService
from app.infrastructure.security.password_hasher import BcryptPasswordHasher
from app.infrastructure.security.refresh_token_issuer import RefreshTokenIssuer


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


def get_password_hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher()


def get_token_service(settings: Settings = Depends(get_settings)) -> JwtTokenService:
    return JwtTokenService(
        secret_key=settings.jwt_secret_key,
        ttl_minutes=settings.access_token_ttl_minutes,
    )


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresUserRepository:
    return PostgresUserRepository(session)


def get_refresh_token_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresRefreshTokenRepository:
    return PostgresRefreshTokenRepository(session)


def get_audit_logger(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresAuditLogRepository:
    return PostgresAuditLogRepository(session)


def get_refresh_token_issuer(
    refresh_repo: PostgresRefreshTokenRepository = Depends(get_refresh_token_repository),
    password_hasher: BcryptPasswordHasher = Depends(get_password_hasher),
    settings: Settings = Depends(get_settings),
) -> RefreshTokenIssuer:
    return RefreshTokenIssuer(
        store=refresh_repo,
        password_hasher=password_hasher,
        ttl_days=settings.refresh_token_ttl_days,
    )


def get_login_use_case(
    session: AsyncSession = Depends(get_db_session),
    user_repository: PostgresUserRepository = Depends(get_user_repository),
    password_hasher: BcryptPasswordHasher = Depends(get_password_hasher),
    token_service: JwtTokenService = Depends(get_token_service),
    refresh_token_issuer: RefreshTokenIssuer = Depends(get_refresh_token_issuer),
    audit_logger: PostgresAuditLogRepository = Depends(get_audit_logger),
    settings: Settings = Depends(get_settings),
) -> LoginUseCase:
    return LoginUseCase(
        user_repository=user_repository,
        password_hasher=password_hasher,
        token_service=token_service,
        refresh_token_issuer=refresh_token_issuer,
        login_state_repository=PostgresLoginStateRepository(session),
        audit_logger=audit_logger,
        failed_login_threshold=settings.failed_login_threshold,
        lockout_minutes=settings.lockout_minutes,
    )


def get_verify_token_use_case(
    user_repository: PostgresUserRepository = Depends(get_user_repository),
    token_service: JwtTokenService = Depends(get_token_service),
) -> VerifyTokenUseCase:
    return VerifyTokenUseCase(
        user_repository=user_repository,
        token_service=token_service,
    )


def get_refresh_token_use_case(
    user_repository: PostgresUserRepository = Depends(get_user_repository),
    refresh_token_repository: PostgresRefreshTokenRepository = Depends(
        get_refresh_token_repository,
    ),
    refresh_token_issuer: RefreshTokenIssuer = Depends(get_refresh_token_issuer),
    password_hasher: BcryptPasswordHasher = Depends(get_password_hasher),
    token_service: JwtTokenService = Depends(get_token_service),
) -> RefreshTokenUseCase:
    return RefreshTokenUseCase(
        user_repository=user_repository,
        refresh_token_repository=refresh_token_repository,
        refresh_token_issuer=refresh_token_issuer,
        password_hasher=password_hasher,
        token_service=token_service,
    )


def get_list_users_use_case(
    user_repository: PostgresUserRepository = Depends(get_user_repository),
) -> ListUsersUseCase:
    return ListUsersUseCase(user_repository)


def get_set_user_active_use_case(
    user_repository: PostgresUserRepository = Depends(get_user_repository),
    audit_logger: PostgresAuditLogRepository = Depends(get_audit_logger),
) -> SetUserActiveUseCase:
    return SetUserActiveUseCase(user_repository, audit_logger)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    use_case: VerifyTokenUseCase = Depends(get_verify_token_use_case),
) -> User:
    try:
        return await use_case.execute(token)
    except (InactiveUserError, InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from exc


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if _role_value(current_user.role) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PermissionDeniedError.detail,
        )
    return current_user


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)

