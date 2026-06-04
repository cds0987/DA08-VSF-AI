from dataclasses import dataclass
from enum import Enum
from typing import Optional


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: UserRole | str
    is_active: bool
    department: str
    hashed_password: Optional[str] = None
    auth_provider: str = "local"

