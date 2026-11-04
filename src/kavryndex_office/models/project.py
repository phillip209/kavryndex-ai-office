from enum import StrEnum

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kavryndex_office.db import Base
from kavryndex_office.models.common import IdMixin, TimestampMixin, enum_type


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        enum_type(ProjectStatus), default=ProjectStatus.ACTIVE
    )
