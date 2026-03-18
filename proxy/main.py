import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from proxy.config import settings
from proxy.constants import EXCLUDED_HEADERS
from shared.schemas import TrafficEvent

app = FastAPI(title="API Traffic Monitor")


@app.get("/")
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

    # TODO: replace with kafka
    print(event.model_dump(mode="json"))

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=dict(upstream_response.headers),
    )


@app.get("/stats")
async def get_stats() -> dict[str, str]:
    # TODO: return real data from redis
    return {"message": "stats skeleton"}
