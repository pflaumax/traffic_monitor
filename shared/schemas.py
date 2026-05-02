from datetime import UTC, datetime

from pydantic import BaseModel, Field


class TrafficEvent(BaseModel):
    """Traffic event emitted to Kafka for each proxied HTTP request.

    Captures key metrics about the request including client information,
    HTTP method and path, response status, timing, and optional user context.
    """

    client_ip: str
    method: str
    path: str
    status_code: int
    response_time_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    user_id: str | None = None


class PathCount(BaseModel):
    """Individual path with request count."""

    path: str
    count: int


class StatsResponse(BaseModel):
    """Response model for /stats endpoint."""

    total_requests: int
    status_codes: dict[str, int]
    methods: dict[str, int]
    avg_response_time_ms: float
    top_paths: list[PathCount]
