from typing import Literal

from pydantic import BaseModel, Field, EmailStr


class UserItem(BaseModel):
    id: str
    email: str
    role: str
    account_type: Literal["internal", "external"]
    is_active: bool


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: Literal["user", "admin"] = "user"
    account_type: Literal["internal", "external"] = "internal"
    department: str


class UserList(BaseModel):
    items: list[UserItem]
    total: int = Field(ge=0)


class UserActiveResponse(BaseModel):
    id: str
    is_active: bool

