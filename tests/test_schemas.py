from datetime import datetime, timezone

from shared.schemas import TrafficEvent
from shared.topics import TOPIC_HTTP_TRAFFIC


def test_traffic_event_defaults():
    event = TrafficEvent(
        client_ip="127.0.0.1",
        method="GET",
        path="/test",
        status_code=200,
        response_time_ms=12.5,
    )
    assert event.user_id is None
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo == timezone.utc


def test_traffic_event_with_user():
    event = TrafficEvent(
        client_ip="10.0.0.1",
        method="POST",
        path="/proxy/post",
        status_code=201,
        response_time_ms=55.0,
        user_id="user123",
    )
    assert event.user_id == "user123"


def test_traffic_event_serialization():
    event = TrafficEvent(
        client_ip="127.0.0.1",
        method="GET",
        path="/test",
        status_code=200,
        response_time_ms=10.0,
    )
    data = event.model_dump(mode="json")
    assert isinstance(data, dict)
    assert data["client_ip"] == "127.0.0.1"
    assert "timestamp" in data


def test_topic_constant():
    assert TOPIC_HTTP_TRAFFIC == "http.traffic"
