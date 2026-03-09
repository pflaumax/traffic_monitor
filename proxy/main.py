from fastapi import FastAPI
from shared.schemas import TrafficEvent

app = FastAPI(title="API Traffic Monitor")


@app.get("/")
async def healthcheck():
    return {"status": "ok"}


@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_handler(path: str):
    event = TrafficEvent(
        client_ip="127.0.0.1",
        method="GET",
        path=f"/{path}",
        status_code=200,
        response_time_ms=0.0,
    )
    return {"message": "proxy skeleton", "path": path, "event": event.model_dump()}


@app.get("/stats")
async def get_stats():
    return {"message": "stats skeleton"}