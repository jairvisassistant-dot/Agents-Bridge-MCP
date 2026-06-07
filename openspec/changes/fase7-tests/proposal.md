# Proposal: Fase 7 — Tests faltantes

## Intent
Add comprehensive test coverage for the Phase 7 features that are already implemented in production code but lack tests:
- 7.2 Skill restrictions enforcement
- 7.3 Task dependencies (depends_on)
- 7.4 CRUD operations (plan.update/archive/delete, task.update/delete)

## Scope
One new test file: `tests/test_features.py` (~300-400 lines)
No production code changes needed — all features are already implemented.

## Approach
Write integration tests using the existing `create_server()` + `_call()` pattern (same as `test_permissions.py` and `test_edge_cases.py`).
Each feature group gets its own test class with shared fixtures.

## Risks
- `_restrictions` and `_agent_role` are injected by server.py — tests need to match the injection logic
- `MAX_REVIEW_CYCLES = 3` means tests need 4 review cycles to verify the limit (can optimize by mocking if needed)
- depends_on circular detection walks the chain in a loop — no infinite loop risk with uuid IDs
