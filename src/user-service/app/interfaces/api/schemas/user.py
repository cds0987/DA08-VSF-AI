from typing import Literal

from pydantic import BaseModel, Field


class UserItem(BaseModel):
    id: str
    email: str
    role: str
    account_type: Literal["internal", "external"]
    is_active: bool


class UserList(BaseModel):
    items: list[UserItem]
    total: int = Field(ge=0)


class UserActiveResponse(BaseModel):
    id: str
    is_active: bool

