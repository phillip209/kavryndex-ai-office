from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from kavryndex_office.models import ProjectStatus

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


class ProjectCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    members: list[str] = Field(
        default_factory=list, description="Slugs de agentes a los que se concede acceso."
    )


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str
    status: ProjectStatus
    created_at: datetime


class MembershipChange(BaseModel):
    agent_slugs: list[str] = Field(min_length=1)
