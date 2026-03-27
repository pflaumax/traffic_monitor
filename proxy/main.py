import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from proxy.config import settings
from proxy.constants import EXCLUDED_HEADERS
from proxy.kafka_producer import emit_event, start_producer, stop_producer
from shared.schemas import TrafficEvent

logger = logging.getLogger(__name__)


async def _emit_safe(app, event_dict: dict) -> None:
    try:
        await emit_event(app, event_dict)
    except Exception as e:
        logger.error("Failed to emit Kafka event: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_producer(app)
    yield
    await stop_producer(app)


app = FastAPI(title="API Traffic Monitor", lifespan=lifespan)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route(
    "/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def proxy_handler(path: str, request: Request) -> Response:
    body = await request.body()
    start = time.perf_counter()

    try:
        async with httpx.AsyncClient() as client:
            upstream_response = await client.request(
                method=request.method,
                url=f"{settings.upstream_base_url}/{path}",
                headers={
                    k: v
                    for k, v in request.headers.items()
                    if k.lower() not in EXCLUDED_HEADERS
                },
                content=body,
                params=dict(request.query_params),
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Upstream unreachable: {e}")

    event = TrafficEvent(
        client_ip=request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else "unknown"),
        method=request.method,
        path=f"/{path}",
        status_code=upstream_response.status_code,
        response_time_ms=round((time.perf_counter() - start) * 1000, 2),
        user_id=request.headers.get("x-user-id"),
    )

    asyncio.create_task(_emit_safe(request.app, event.model_dump(mode="json")))

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=dict(upstream_response.headers),
    )


@app.get("/stats")
async def get_stats() -> dict[str, str]:
    # TODO: return real data from redis
    return {"message": "stats skeleton"}
