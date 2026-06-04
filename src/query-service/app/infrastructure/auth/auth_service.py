from dataclasses import dataclass

import jwt
from fastapi import HTTPException, status

from app.infrastructure.config import Settings


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    role: str
    department: str
    is_active: bool = True


MOCK_TOKENS: dict[str, AuthenticatedUser] = {
    "mock-user-hr": AuthenticatedUser(
        id="11111111-1111-4111-8111-111111111111",
        email="hr.user@company.com",
        role="user",
        department="HR",
    ),
    "mock-user-finance": AuthenticatedUser(
        id="22222222-2222-4222-8222-222222222222",
        email="finance.user@company.com",
        role="user",
        department="Finance",
    ),
    "mock-admin": AuthenticatedUser(
        id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        email="admin@company.com",
        role="admin",
        department="Admin",
    ),
}


class AuthService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def authenticate(self, authorization: str | None) -> AuthenticatedUser:
        token = self._extract_bearer_token(authorization)
        if self._settings.auth_mode == "mock":
            user = MOCK_TOKENS.get(token)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid mock token",
                )
            return user
        if self._settings.auth_mode == "jwt":
            return self._authenticate_jwt(token)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unsupported AUTH_MODE",
        )

    def _authenticate_jwt(self, token: str) -> AuthenticatedUser:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret_key,
                algorithms=[self._settings.jwt_algorithm],
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            ) from exc

        user_id = payload.get("sub") or payload.get("id") or payload.get("user_id")
        role = payload.get("role")
        if not user_id or not role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing required claims",
            )
        return AuthenticatedUser(
            id=str(user_id),
            email=str(payload.get("email", "")),
            role=str(role),
            department=str(payload.get("department", "")),
            is_active=bool(payload.get("is_active", True)),
        )

    @staticmethod
    def _extract_bearer_token(authorization: str | None) -> str:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header",
            )
        return token
