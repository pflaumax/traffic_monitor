import time
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
from shared.schemas import TrafficEvent

app = FastAPI(title="API Traffic Monitor")

UPSTREAM_BASE_URL = "https://httpbin.org"
EXCLUDED_HEADERS = frozenset(("host", "content-length"))


@app.get("/")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_handler(path: str, request: Request) -> Response:
    body = await request.body()

    start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        upstream_response = await client.request(
            method=request.method,
            url=f"{UPSTREAM_BASE_URL}/{path}",
            headers={k: v for k, v in request.headers.items() if k.lower() not in EXCLUDED_HEADERS},
            content=body,
            params=dict(request.query_params),
        )


    event = TrafficEvent(
        client_ip=request.headers.get("x-forwarded-for", request.client.host),
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