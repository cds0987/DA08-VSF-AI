from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from app.application.security import AccessToken
from app.domain.entities.user import User


class JwtTokenService:
    def __init__(self, secret_key: str, ttl_minutes: int = 15) -> None:
        self.secret_key = secret_key
        self.ttl_minutes = ttl_minutes

    def create_access_token(self, user: User) -> AccessToken:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self.ttl_minutes)
        jti = str(uuid4())
        payload = {
            "sub": str(user.id),
            "user_id": str(user.id),
            "role": _role_value(user.role),
            "account_type": user.account_type,
            "department": user.department,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": expires_at,
        }
        token = jwt.encode(payload, self.secret_key, algorithm="HS256")
        return AccessToken(token=token, jti=jti, expires_at=expires_at)

    def decode_access_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
        except JWTError as exc:
            raise ValueError("invalid token") from exc

        if (
            not payload.get("sub")
            or not payload.get("jti")
            or not payload.get("account_type")
        ):
            raise ValueError("missing required claims")
        return payload


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)

