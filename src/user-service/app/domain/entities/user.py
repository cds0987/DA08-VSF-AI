from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: UserRole | str
    is_active: bool = True
    account_type: Literal["internal", "external"] = "internal"
    hashed_password: Optional[str] = None
    auth_provider: str = "local"

