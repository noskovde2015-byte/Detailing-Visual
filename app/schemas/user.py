import uuid
from datetime import datetime

from pydantic import BaseModel


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    is_admin: bool
    balance: int
    created_at: datetime
