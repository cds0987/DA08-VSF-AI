from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.entities.user import User


@dataclass(frozen=True)
class AccessToken:
    token: str
    jti: str
    expires_at: datetime


class PasswordHasher(Protocol):
    def hash(self, plain_text: str) -> str:
        ...

    def verify(self, plain_text: str, hashed: str) -> bool:
        ...


class TokenService(Protocol):
    def create_access_token(self, user: User) -> AccessToken:
        ...

    def decode_access_token(self, token: str) -> dict:
        ...

