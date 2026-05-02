## Why

The API Traffic Monitor project has a fully implemented proxy core (commit `a32b980`) but lacks formal specifications, architecture documentation, and a structured task backlog. Without these artifacts, the remaining roadmap (rate limiting, Kafka consumer, dashboard, expanded tests) has no clear implementation contract, and open architectural decisions remain unresolved.

## What Changes

- Generate formal project specification covering problem statement, success criteria, and constraints
- Generate architecture design document with component diagram, data flow, failure modes, and open questions
- Generate complete API reference for all endpoints (`/health`, `/proxy/{path}`, `/stats`)
- Generate data model documentation for `TrafficEvent`, Redis key schema, and Kafka message format
- Generate structured task backlog with DONE/TODO/BUG/DECISION tasks derived from commit history and roadmap
- Generate dashboard UI design document for the planned `dashboard/` service
- Generate environment and configuration reference

## Capabilities

### New Capabilities

- `project-spec`: Formal specification of the API Traffic Monitor — problem, solution, principles, success criteria, and constraints
- `architecture`: System architecture design — component diagram, data flow, failure modes, scalability notes, and open architectural questions
- `api-reference`: HTTP endpoint documentation for `/health`, `/proxy/{path}`, and `/stats`
- `data-models`: Pydantic model specs, Redis key schema, and Kafka message format documentation
- `task-backlog`: Structured implementation task list covering DONE commits, TODO roadmap items, BUG issues, and DECISION items
- `dashboard-design`: UI design and implementation plan for the real-time traffic visualization dashboard (`dashboard/` service)
- `environment-config`: Environment variables reference, Docker Compose service config, and local dev setup guide

### Modified Capabilities

<!-- None — this is a documentation-only change; no existing spec-level behavior is changing -->

## Impact

- Creates `openspec/specs/` entries for all 7 capabilities listed above
- No changes to production code (`proxy/`, `shared/`, `tests/`)
- Provides the implementation contract needed before starting roadmap work (rate limiter, consumer, dashboard)
- Resolves or formally documents all open architecture questions from the master project summary
