import asyncio
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from proxy.auth import authenticate_user, create_access_token, require_auth
from proxy.config import settings
from proxy.constants import EXCLUDED_HEADERS, EXCLUDED_RESPONSE_HEADERS
from proxy.kafka_producer import emit_event, start_producer, stop_producer
from proxy.rate_limiter import check_rate_limit
from proxy.redis_client import start_redis, stop_redis
from shared.schemas import (
    HistoryPoint,
    PathCount,
    StatsHistoryResponse,
    StatsResponse,
    TrafficEvent,
)

logger.remove()
logger.add(
    sys.stderr,
    format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} | {level} | {name}:{function}:{line} | {message}",
    level="INFO",
    serialize=True,  # emit as JSON lines
)

REQUEST_COUNT = Counter(
    "proxy_requests_total",
    "Total number of proxied requests",
    ["method", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "proxy_request_duration_seconds",
    "Histogram of upstream response latency in seconds",
    ["method"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
RATE_LIMITED_COUNT = Counter(
    "proxy_rate_limited_total",
    "Number of requests rejected by the rate limiter",
)


async def _emit_safe(app, event_dict: dict) -> None:
    try:
        await emit_event(app, event_dict)
    except Exception as e:
        logger.error("Failed to emit Kafka event: {error}", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_producer(app)
    await start_redis(app)
    app.state.http_client = httpx.AsyncClient()
    logger.info("Proxy service started")
    yield
    await app.state.http_client.aclose()
    await stop_producer(app)
    await stop_redis(app)
    logger.info("Proxy service stopped")


app = FastAPI(title="API Traffic Monitor", lifespan=lifespan)


@app.post("/auth/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):  # noqa: B008
    """Exchange username + password for a JWT access token."""
    if not authenticate_user(form.username, form.password):
        logger.warning("Failed login attempt for username={username}", username=form.username)
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=form.username)
    logger.info("Issued token for username={username}", username=form.username)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics() -> PlainTextResponse:
    """Expose Prometheus metrics in the standard exposition format."""
    return PlainTextResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
        RATE_LIMITED_COUNT.inc()
        logger.warning("Rate limit exceeded for client_ip={client_ip}", client_ip=client_ip)
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")

    body = await request.body()
    start = time.perf_counter()

    try:
        upstream_response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{settings.upstream_base_url}/{path}",
            headers={k: v for k, v in request.headers.items() if k.lower() not in EXCLUDED_HEADERS},
            content=body,
            params=list(request.query_params.multi_items()),
        )
    except httpx.RequestError as e:
        logger.error("Upstream request failed for path=/{path}: {error}", path=path, error=str(e))
        raise HTTPException(status_code=502, detail=f"Upstream unreachable: {e}") from e

    elapsed = time.perf_counter() - start

    REQUEST_COUNT.labels(
        method=request.method,
        status_code=str(upstream_response.status_code),
    ).inc()
    REQUEST_LATENCY.labels(method=request.method).observe(elapsed)

    logger.debug(
        "Proxied {method} /{path} → {status} in {ms:.1f}ms",
        method=request.method,
        path=path,
        status=upstream_response.status_code,
        ms=elapsed * 1000,
    )

    event = TrafficEvent(
        client_ip=client_ip,
        method=request.method,
        path=f"/{path}",
        status_code=upstream_response.status_code,
        response_time_ms=round(elapsed * 1000, 2),
        user_id=request.headers.get("x-user-id"),
    )
    event_dict = event.model_dump(mode="json")

    # Store task reference to prevent premature garbage collection
    emit_task = asyncio.create_task(_emit_safe(request.app, event_dict))
    emit_task.add_done_callback(lambda t: None)

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
async def get_stats(
    request: Request,
    _current_user: str = Depends(require_auth),
) -> StatsResponse:
    """Return aggregated traffic metrics. Requires a valid Bearer token."""
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
        logger.error("Redis unavailable for /stats: {error}", error=str(e))
        raise HTTPException(status_code=503, detail="Stats unavailable: Redis unreachable") from e

    total = int(total_raw) if total_raw else 0
    time_sum = float(time_sum_raw) if time_sum_raw else 0.0
    time_count = int(time_count_raw) if time_count_raw else 0

    return StatsResponse(
        total_requests=total,
        status_codes={k: int(v) for k, v in status_raw.items()},
        methods={k: int(v) for k, v in methods_raw.items()},
        avg_response_time_ms=round(time_sum / time_count, 2) if time_count else 0.0,
        top_paths=[PathCount(path=path, count=int(score)) for path, score in top_paths_raw],
    )


@app.get("/stats/history", response_model=StatsHistoryResponse)
async def get_stats_history(
    request: Request,
    limit: int = 60,
    _current_user: str = Depends(require_auth),
) -> StatsHistoryResponse:
    """Get time-series request count history for dashboard line chart. Requires a valid Bearer token."""
    redis = request.app.state.redis
    try:
        history_raw = await redis.zrevrange("stats:history", 0, limit - 1, withscores=True)
    except Exception as e:
        logger.error("Redis unavailable for /stats/history: {error}", error=str(e))
        raise HTTPException(
            status_code=503, detail="Stats history unavailable: Redis unreachable"
        ) from e

    history = [
        HistoryPoint(timestamp=int(timestamp), count=int(count))
        for timestamp, count in reversed(history_raw)
    ]

    return StatsHistoryResponse(history=history)
