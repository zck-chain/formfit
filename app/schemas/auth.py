"""鉴权相关 Pydantic 模型。"""
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    nickname: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str | None = None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


TokenOut.model_rebuild()
