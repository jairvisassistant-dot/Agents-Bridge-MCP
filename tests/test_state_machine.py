"""Tests for the Agent Bridge state machine — validates every transition."""

import pytest

from agent_bridge.state.state_machine import (
    PLAN_TRANSITIONS,
    REVIEW_TRANSITIONS,
    TASK_TRANSITIONS,
    THREAD_TRANSITIONS,
    TransitionError,
    can_transition,
    validate_plan_transition,
    validate_review_transition,
    validate_task_transition,
    validate_thread_transition,
)


# ── Plan transition tests ─────────────────────────────────────────

class TestPlanTransitions:
    def test_idle_to_planning(self):
        validate_plan_transition("idle", "planning")  # should not raise

    def test_planning_to_tasks_ready(self):
        validate_plan_transition("planning", "tasks_ready")

    def test_planning_back_to_idle(self):
        validate_plan_transition("planning", "idle")  # reset

    def test_tasks_ready_to_in_progress(self):
        validate_plan_transition("tasks_ready", "in_progress")

    def test_in_progress_to_completed(self):
        validate_plan_transition("in_progress", "completed")

    def test_invalid_idle_to_completed(self):
        with pytest.raises(TransitionError, match="plan cannot go from 'idle' to 'completed'"):
            validate_plan_transition("idle", "completed")

    def test_invalid_completed_to_anything(self):
        with pytest.raises(TransitionError):
            validate_plan_transition("completed", "idle")
        with pytest.raises(TransitionError):
            validate_plan_transition("completed", "planning")

    def test_all_states_covered(self):
        """Every plan status appears at least once in the transition map."""
        from agent_bridge.state.models import PlanStatus
        import typing
        for status in typing.get_args(PlanStatus):
            assert status in PLAN_TRANSITIONS, f"Missing plan status: {status}"


# ── Task transition tests ─────────────────────────────────────────

class TestTaskTransitions:
    def test_pending_to_in_progress(self):
        validate_task_transition("pending", "in_progress")

    def test_in_progress_to_review(self):
        validate_task_transition("in_progress", "review")

    def test_review_to_approved(self):
        validate_task_transition("review", "approved")

    def test_review_to_changes_requested(self):
        validate_task_transition("review", "changes_requested")

    def test_changes_requested_to_review(self):
        validate_task_transition("changes_requested", "review")

    def test_invalid_pending_to_approved(self):
        with pytest.raises(TransitionError):
            validate_task_transition("pending", "approved")

    def test_invalid_approved_to_anything(self):
        with pytest.raises(TransitionError):
            validate_task_transition("approved", "pending")

    def test_triple_loop(self):
        """Full cycle: pending -> in_progress -> review -> changes_requested -> review -> approved"""
        validate_task_transition("pending", "in_progress")
        validate_task_transition("in_progress", "review")
        validate_task_transition("review", "changes_requested")
        validate_task_transition("changes_requested", "review")  # re-submit
        validate_task_transition("review", "approved")

    def test_all_states_covered(self):
        from agent_bridge.state.models import TaskStatus
        import typing
        for status in typing.get_args(TaskStatus):
            assert status in TASK_TRANSITIONS, f"Missing task status: {status}"


# ── Review transition tests ───────────────────────────────────────

class TestReviewTransitions:
    def test_pending_to_in_review(self):
        validate_review_transition("pending", "in_review")

    def test_in_review_to_approved(self):
        validate_review_transition("in_review", "approved")

    def test_in_review_to_changes_requested(self):
        validate_review_transition("in_review", "changes_requested")

    def test_invalid_pending_to_approved(self):
        with pytest.raises(TransitionError):
            validate_review_transition("pending", "approved")

    def test_all_states_covered(self):
        from agent_bridge.state.models import ReviewStatus
        import typing
        for status in typing.get_args(ReviewStatus):
            assert status in REVIEW_TRANSITIONS, f"Missing review status: {status}"


# ── Thread transition tests ───────────────────────────────────────

class TestThreadTransitions:
    def test_open_to_resolved(self):
        validate_thread_transition("open", "resolved")

    def test_invalid_resolved_to_open(self):
        with pytest.raises(TransitionError):
            validate_thread_transition("resolved", "open")

    def test_all_states_covered(self):
        from agent_bridge.state.models import ThreadStatus
        import typing
        for status in typing.get_args(ThreadStatus):
            assert status in THREAD_TRANSITIONS, f"Missing thread status: {status}"


# ── can_transition helper ─────────────────────────────────────────

class TestCanTransition:
    def test_valid(self):
        assert can_transition("task", "pending", "in_progress") is True
        assert can_transition("plan", "idle", "planning") is True

    def test_invalid(self):
        assert can_transition("task", "pending", "approved") is False
        assert can_transition("plan", "completed", "idle") is False

    def test_unknown_entity(self):
        assert can_transition("foo", "a", "b") is False

    def test_unknown_state(self):
        assert can_transition("task", "nonexistent", "pending") is False
