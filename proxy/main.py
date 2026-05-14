import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from proxy.config import settings
from proxy.constants import EXCLUDED_HEADERS, EXCLUDED_RESPONSE_HEADERS
from proxy.kafka_producer import emit_event, start_producer, stop_producer
from proxy.rate_limiter import check_rate_limit
from proxy.redis_client import start_redis, stop_redis, update_stats
from shared.schemas import PathCount, StatsResponse, TrafficEvent

logger = logging.getLogger(__name__)


async def _emit_safe(app, event_dict: dict) -> None:
    try:
        await emit_event(app, event_dict)
    except Exception as e:
        logger.error("Failed to emit Kafka event: %s", e)


async def _update_stats_safe(app, event_dict: dict) -> None:
    try:
        await update_stats(app.state.redis, event_dict)
    except Exception as e:
        logger.error("Failed to update Redis stats: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_producer(app)
    await start_redis(app)
    app.state.http_client = httpx.AsyncClient()
    yield
    await app.state.http_client.aclose()
    await stop_producer(app)
    await stop_redis(app)


app = FastAPI(title="API Traffic Monitor", lifespan=lifespan)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route(
    "/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy_handler(path: str, request: Request) -> Response:
    client_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else "unknown"
    )
    allowed = await check_rate_limit(
        request.app.state.redis, client_ip, settings.rate_limit_per_minute
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")

    body = await request.body()
    start = time.perf_counter()

    try:
        upstream_response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{settings.upstream_base_url}/{path}",
            headers={k: v for k, v in request.headers.items() if k.lower() not in EXCLUDED_HEADERS},
            content=body,
            params=str(request.query_params),
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Upstream unreachable: {e}") from e

    event = TrafficEvent(
        client_ip=request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else "unknown"),
        method=request.method,
        path=f"/{path}",
        status_code=upstream_response.status_code,
        response_time_ms=round((time.perf_counter() - start) * 1000, 2),
        user_id=request.headers.get("x-user-id"),
    )
    event_dict = event.model_dump(mode="json")

    # Store task references to prevent premature garbage collection
    emit_task = asyncio.create_task(_emit_safe(request.app, event_dict))
    stats_task = asyncio.create_task(_update_stats_safe(request.app, event_dict))

    # Add done callbacks to clean up task references
    emit_task.add_done_callback(lambda t: None)
    stats_task.add_done_callback(lambda t: None)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers={
            k: v
            for k, v in upstream_response.headers.items()
            if k.lower() not in EXCLUDED_RESPONSE_HEADERS
        },
    )


@app.get("/stats", response_model=StatsResponse)
async def get_stats(request: Request) -> StatsResponse:
    redis = request.app.state.redis
    try:
        (
            total_raw,
            status_raw,
            methods_raw,
            time_sum_raw,
            time_count_raw,
            top_paths_raw,
        ) = await asyncio.gather(
            redis.get("stats:total_requests"),
            redis.hgetall("stats:status_codes"),
            redis.hgetall("stats:methods"),
            redis.get("stats:response_time_sum"),
            redis.get("stats:response_time_count"),
            redis.zrevrange("stats:top_paths", 0, 9, withscores=True),
        )
    except Exception as e:
        logger.error("Redis unavailable: %s", e)
        return JSONResponse(
            status_code=503, content={"detail": "Stats unavailable: Redis unreachable"}
        )

    total = int(total_raw) if total_raw else 0
    time_sum = float(time_sum_raw) if time_sum_raw else 0.0
    time_count = int(time_count_raw) if time_count_raw else 0

    return StatsResponse(
        total_requests=total,
        status_codes={k.decode(): int(v) for k, v in status_raw.items()},
        methods={k.decode(): int(v) for k, v in methods_raw.items()},
        avg_response_time_ms=round(time_sum / time_count, 2) if time_count else 0.0,
        top_paths=[
            PathCount(path=path.decode(), count=int(score)) for path, score in top_paths_raw
        ],
    )
