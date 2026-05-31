from dataclasses import dataclass
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


@dataclass
class User:
    id: str
    email: str
    role: UserRole
    is_active: bool = True
    department: str = ""                        # dùng để check Secret-level access
    hashed_password: Optional[str] = None       # None nếu đăng nhập qua Microsoft SSO
    auth_provider: str = "local"                # "local" | "microsoft"
