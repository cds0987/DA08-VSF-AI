from abc import ABC, abstractmethod
from typing import Optional
from app.domain.entities.user import User


class UserRepository(ABC):

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """Tìm user theo email (dùng cho login)."""

    @abstractmethod
    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Tìm user theo ID (dùng cho JWT verify)."""

    @abstractmethod
    async def create(self, user: User) -> User:
        """Tạo user mới."""
