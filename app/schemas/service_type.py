import uuid

from pydantic import BaseModel, ConfigDict, Field


class TaskTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    sequence: int = Field(ge=1)
    default_offset_days: int = Field(
        ge=0,
        description="Days after the engagement's start_date that this task is due.",
    )


class TaskTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    sequence: int | None = Field(default=None, ge=1)
    default_offset_days: int | None = Field(default=None, ge=0)


class TaskTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_type_id: uuid.UUID
    title: str
    sequence: int
    default_offset_days: int


class ServiceTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ServiceTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_active: bool | None = None


class ServiceTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    task_templates: list[TaskTemplateResponse] = []
