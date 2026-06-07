# Tasks: Fase 7 — Tests faltantes

## Review Workload Forecast
- Estimated changed lines: ~380 (new file)
- 400-line budget risk: Low
- Chained PRs recommended: No (single focused file)
- Decision needed before apply: No

## ✅ Task 1 — Test infrastructure helpers (tasks.py shared fixtures)

Create the shared `db_path` fixture, `_call()` helper, `_setup_plan_with_task()` and `_make_dev_server()` helpers in the new file.
Also create a `_setup_plan_with_archived_task()` and `_setup_review_cycles()` for the specific test needs.

**Files:**
- `tests/test_features.py`

**Test:** The file must import cleanly and the helpers must be callable.

---

## ✅ Task 2 — TestSkillRestrictions class (7.2)

Implement:
- `test_max_concurrent_tasks_blocks` — 2 pending tasks, claim first → claim second with max_concurrent_tasks=1 → error
- `test_max_concurrent_tasks_allows_within_limit` — max_concurrent_tasks=2, claim 2nd → success
- `test_max_concurrent_tasks_per_agent` — agent A blocked, agent B succeeds
- `test_cannot_approve_own_work_blocks` — same-agent approval blocked
- `test_cannot_approve_own_work_allows_cross_role` — different agent approves
- `test_max_review_cycles_blocks_after_3` — 4th review cycle blocked
- `test_max_review_cycles_allows_within_limit` — 2nd cycle allowed

**Key:** Pass `_restrictions` and `_agent_role` directly in args.

---

## ✅ Task 3 — TestTaskDependencies class (7.3)

Implement:
- `test_create_task_with_depends_on` — creates with `depends_on` param
- `test_create_task_invalid_depends_on` — nonexistent dependency → error
- `test_claim_blocked_by_unapproved_dependency` — dependency in 'pending' → error
- `test_claim_allowed_when_dependency_approved` — dependency 'approved' → success
- `test_circular_dependency_detected` — A→B→A cycle → error

**Key:** Use `_setup_plan_with_task()` for setup, direct DB inserts for the circular chain.

---

## ✅ Task 4 — TestPlanCRUD class (7.4)

Implement:
- `test_plan_update_transition` — plan.update with valid status change
- `test_plan_update_invalid_transition` — plan.update with invalid transition → error
- `test_plan_archive_soft_delete` — plan.archive → plan.get returns archived
- `test_plan_archive_on_completed_fails` — archiving completed plan → error
- `test_plan_delete_cascades` — delete plan with tasks → all gone
- `test_plan_delete_nonexistent` — bad plan_id → error

---

## ✅ Task 5 — TestTaskCRUD class (7.4)

Implement:
- `test_task_update_title_and_description` — update pending task
- `test_task_update_blocks_for_approved` — approved task → error
- `test_task_delete_pending` — delete pending task
- `test_task_delete_blocks_for_approved` — approved task → error

---

## ✅ Task 6 — Run tests and fix any issues

```bash
uv run pytest tests/test_features.py -v
```

Expected: All tests pass.

## ✅ Resultado

```
tests/test_features.py ✓ 26 passed in 10.40s
Full suite: 227 passed in 87.23s
```

### Bonus Fix
`plan.archive`, `plan.delete`, `task.update`, `task.delete` agregados a `allowed_tools` de `architect` y `developer` en `skills/*.json` y `config.py` (hardcoded fallback). Estos tools estaban implementados pero bloqueados por la capa de permisos.
