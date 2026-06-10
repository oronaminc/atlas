import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.sync import SyncStatus, SyncTarget


class SyncStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target: SyncTarget
    last_synced_at: datetime | None
    status: SyncStatus
    last_error: str | None
    checksum: str | None
