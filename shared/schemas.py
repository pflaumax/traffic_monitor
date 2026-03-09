from datetime import datetime, timezone
from pydantic import BaseModel, Field


class TrafficEvent(BaseModel):
    client_ip: str
    method: str
    path: str
    status_code: int
    response_time_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    user_id: str | None = None
