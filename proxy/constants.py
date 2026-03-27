# REQUEST. Headers to exclude when forwarding requests to upstream
EXCLUDED_HEADERS = frozenset(("host", "content-length"))

# RESPONSE. Headers to exclude from upstream response httpx normalizes the body
EXCLUDED_RESPONSE_HEADERS = frozenset(
    (
        "content-encoding",
        "content-length",
        "transfer-encoding",
    )
)
