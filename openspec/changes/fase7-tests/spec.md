# Spec: Fase 7 — Tests faltantes

## Feature 7.2 — Skill Restrictions Enforcement

### Scenario: max_concurrent_tasks blocks when at limit
Given an agent with `_restrictions = {"max_concurrent_tasks": 1}` who is already assigned 1 in_progress task
When the agent calls `task.claim` on another pending task
Then the response MUST contain `"error": "max_concurrent_tasks_reached"`

### Scenario: max_concurrent_tasks allows within limit
Given an agent with `_restrictions = {"max_concurrent_tasks": 2}` who has 1 in_progress task
When the agent calls `task.claim` on another pending task
Then the claim SHOULD succeed with `"status": "in_progress"`

### Scenario: max_concurrent_tasks is per-agent
Given two agents, each with `_restrictions = {"max_concurrent_tasks": 1}`
And agent A has 1 in_progress task
When agent B calls `task.claim` on a pending task
Then the claim SHOULD succeed (limit is per-agent)

### Scenario: cannot_approve_own_work blocks same-role approval
Given an agent with role `"developer"` and `_restrictions = {"cannot_approve_own_work": true}`
And the agent is the assignee of a task in 'review' status
When the agent calls `review.approve`
Then the response MUST contain `"error": "cannot_approve_own_work"`

### Scenario: cannot_approve_own_work allows cross-role approval
Given an agent with role `"architect"` and `_restrictions = {"cannot_approve_own_work": true}`
And a DIFFERENT agent is the task assignee
When the agent calls `review.approve`
Then the approval SHOULD succeed

### Scenario: MAX_REVIEW_CYCLES blocks after 3 changes_requested
Given a task that has been through 3 review cycles (3 `changes_requested` entries)
When `review.start` is called on the 4th cycle
Then the response MUST contain `"error": "max_review_cycles_reached"`

### Scenario: MAX_REVIEW_CYCLES allows within limit
Given a task with 2 review cycles (2 `changes_requested` entries)
When `review.start` is called
Then it SHOULD succeed with `"status": "in_review"`

## Feature 7.3 — Task Dependencies

### Scenario: create task with depends_on
Given a plan with an existing task A
When task.create is called with `depends_on: task_A_id`
Then the task SHOULD be created with `"status": "pending"`
And the `depends_on` field SHOULD reference task A

### Scenario: create task with invalid depends_on
Given no task with ID "nonexistent"
When task.create is called with `depends_on: "nonexistent"`
Then the response MUST contain `"error": "dependency task 'nonexistent' not found"`

### Scenario: claim blocked when dependency not approved
Given a task B that depends_on task A
And task A is in 'pending' status
When an agent calls `task.claim` on task B
Then the response MUST contain `"error": "dependency_not_approved"`

### Scenario: claim allowed when dependency is approved
Given a task B that depends_on task A
And task A has been approved
When an agent calls `task.claim` on task B
Then the claim SHOULD succeed with `"status": "in_progress"`

### Scenario: circular dependency detected
Given task A depends_on task B
And task B depends_on task A (creating a cycle)
When an agent tries to claim task A
Then the response MUST contain `"error": "circular_dependency"`

## Feature 7.4 — CRUD Operations

### Scenario: plan.update transitions status
Given a plan in 'planning' status
When `plan.update` is called with `status: "tasks_ready"`
Then the response SHOULD contain `"status": "tasks_ready"`

### Scenario: plan.update invalid transition
Given a plan in 'idle' status
When `plan.update` is called with `status: "completed"`
Then the response MUST contain an error about invalid transition

### Scenario: plan.archive soft-deletes
Given a plan in 'in_progress' status
When `plan.archive` is called
Then the response SHOULD contain `"status": "archived"`
And `plan.get` SHOULD still return the plan with `"status": "archived"`

### Scenario: plan.archive on completed plan
Given a plan in 'completed' status
When `plan.archive` is called
Then the response MUST contain an error "plan is already completed, cannot archive"

### Scenario: plan.delete removes plan and tasks
Given a plan with 2 tasks
When `plan.delete` is called
Then the response SHOULD contain `"deleted": true`
And `plan.get` SHOULD return `"error": "plan not found"`
And task.list SHOULD return empty for that plan_id

### Scenario: plan.delete on nonexistent plan
Given no plan with the given ID
When `plan.delete` is called
Then the response MUST contain `"error": "plan not found"`

### Scenario: task.update changes title and description
Given a pending task
When `task.update` is called with a new title
Then the response SHOULD contain the new title
And `task.get` SHOULD return the updated title

### Scenario: task.update blocks for approved tasks
Given an approved task
When `task.update` is called
Then the response MUST contain an error "can only update pending or in_progress tasks"

### Scenario: task.delete removes pending task
Given a pending task
When `task.delete` is called
Then the response SHOULD contain `"deleted": true`
And `task.get` SHOULD return `"error": "task not found"`

### Scenario: task.delete blocks for approved task
Given an approved task
When `task.delete` is called
Then the response MUST contain an error "can only delete pending or in_progress tasks"

## Non-goals
- VSCode extension tests (7.5) — TypeScript testing requires separate setup
- E2E or browser tests
- Load/stress tests (covered in test_stress.py)
