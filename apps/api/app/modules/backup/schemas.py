from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.backup.models import BackupStatus


class BackupSettingsIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class ConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class BackupStatusOut(BaseModel):
    email: str | None
    status: BackupStatus | None
    last_sent_at: datetime | None
    last_error_ar: str | None
    consecutive_failures: int
    manual_sends_left: int
    mail_configured: bool
