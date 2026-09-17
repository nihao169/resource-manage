from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict

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

