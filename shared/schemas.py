from pydantic import BaseModel
from typing import Optional


class TrafficEvent(BaseModel):
    client_ip: str
    method: str
    path: str
    status_code: int
    response_time_ms: float
    user_id: Optional[str] = None
