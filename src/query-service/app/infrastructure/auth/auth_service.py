import httpx
import jwt
from fastapi import HTTPException, status

from app.application.ports import AuthenticatedUser
from app.infrastructure.config import Settings


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

    async def authenticate(self, authorization: str | None) -> AuthenticatedUser:
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
        if self._settings.auth_mode == "user_service":
            return await self._authenticate_user_service(authorization)
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

    async def _authenticate_user_service(self, authorization: str | None) -> AuthenticatedUser:
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.user_service_url,
                timeout=self._settings.auth_http_timeout_seconds,
            ) as client:
                response = await client.get("/auth/me", headers={"Authorization": authorization or ""})
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="user-service unavailable",
            ) from exc

        if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="user-service authentication failed",
            )

        payload = response.json()
        user_id = payload.get("id")
        role = payload.get("role")
        if not user_id or not role:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="user-service returned invalid user profile",
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
