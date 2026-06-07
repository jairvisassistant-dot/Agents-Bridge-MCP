# Design: Fase 7 — Tests faltantes

## Test File Structure

Single new file: `tests/test_features.py`

### Classes

```
TestSkillRestrictions        → 7.2 tests (6 tests)
TestTaskDependencies         → 7.3 tests (5 tests)
TestPlanCRUD                 → 7.4 plan tests (4 tests)
TestTaskCRUD                 → 7.4 task tests (4 tests)
```

### Shared Fixtures + Helpers

Reuse the same pattern from `test_edge_cases.py`:
- `db_path` fixture — temp SQLite DB
- `_call()` method — CallToolRequest → parsed JSON response
- `_setup_plan_with_task()` helper — direct DB insert for plan + task
- `_make_dev_server()` helper — create_server + heartbeat

### Key Technique: Restrictions Injection

`_restrictions` and `_agent_role` are normally injected by `server.py` from the skill config.
In tests, we pass them **directly in the tool args** since the handler reads `args.get("_restrictions", {})` and `args.get("_agent_role")`.

Example:
```python
await self._call(server, "task.claim", {
    "task_id": task_id,
    "_agent_role": "developer",
    "_restrictions": {"max_concurrent_tasks": 1},
})
```

### Review Cycles Test Strategy

To test MAX_REVIEW_CYCLES=3 without excessive boilerplate:
1. Create a task, claim → submit → review.start → review.request_changes (3 times)
2. On 4th review.start → expect "max_review_cycles_reached"

For the "within limit" test: 2 cycles → review.start succeeds.

### Circular Dependency Test

Set up via direct DB inserts:
- Task A depends_on Task B
- Task B depends_on Task A
- Claim A → expect "circular_dependency"

### Plan CRUD: archive/get/delete verification

After plan.archive → verify plan.get still returns it (soft-delete)
After plan.delete → verify plan.get returns error (hard-delete)

### Dependency Compatibility

These tests do NOT mock anything — they exercise the full MCP server handler
with real SQLite (temp file), matching production behavior exactly.
