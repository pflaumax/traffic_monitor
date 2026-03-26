## Fast tests 

# 1. healthcheck
curl http://localhost:8000/

# 2. proxy
curl http://localhost:8000/proxy/get

# 3. query params
curl "http://localhost:8000/proxy/get?foo=bar"

# 4. x-forwarded-for
curl -H "x-forwarded-for: 1.2.3.4" http://localhost:8000/proxy/get

# 5. x-user-id
curl -H "x-user-id: user123" http://localhost:8000/proxy/get

# 6. POST body
curl -X POST http://localhost:8000/proxy/post \
  -H "Content-Type: application/json" \
  -d '{"hello": "world"}'
