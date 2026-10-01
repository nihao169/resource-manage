from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Envelope(ContractModel, Generic[T]):
    data: T
    request_id: UUID

class Page(ContractModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int

class Pagination(ContractModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

