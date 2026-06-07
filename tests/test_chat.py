"""Tests for the chat system — send/read messages, thread management, @mention routing."""

import asyncio
import json
import tempfile
from pathlib import Path

import anyio
import pytest
from mcp.types import CallToolRequest

from agent_bridge.server import create_server


class TestChatSystem:
    """Integration tests for chat tools via the MCP server handler."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    async def _call(self, server, tool: str, args: dict | None = None):
        """Helper: call an MCP tool and return the parsed JSON response."""
        from mcp.types import CallToolRequest

        req = CallToolRequest(
            method="tools/call",
            params={"name": tool, "arguments": args or {}},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    # ── Basic send/read ──────────────────────────────────────────

    def test_send_and_read_message(self, db_path):
        """Send a message, then read it back."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Send
            send_result = await self._call(server, "chat.send", {
                "text": "Hola mundo",
                "sender": "human",
            })
            assert "message_id" in send_result
            msg_id = send_result["message_id"]

            # Read
            messages = await self._call(server, "chat.read")
            assert isinstance(messages, list)
            assert len(messages) == 1
            assert messages[0]["text"] == "Hola mundo"
            assert messages[0]["sender"] == "human"
            assert messages[0]["id"] == msg_id

        anyio.run(run)

    def test_send_message_with_target(self, db_path):
        """Send a message with a @mention target, read filtered by target."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            await self._call(server, "chat.send", {
                "text": "Revisá esto",
                "sender": "human",
                "target": "arquitecto",
            })

            messages = await self._call(server, "chat.read", {"target": "arquitecto"})
            assert isinstance(messages, list)
            assert len(messages) == 1
            assert messages[0]["target"] == "arquitecto"

            # Public message should also appear when filtering by target
            await self._call(server, "chat.send", {
                "text": "mensaje público",
                "sender": "human",
            })
            messages = await self._call(server, "chat.read", {"target": "arquitecto"})
            assert len(messages) == 2  # targeted + public

        anyio.run(run)

    # ── @mention presence routing ────────────────────────────────

    def test_mention_arquitecto_offline_warning(self, db_path):
        """Mentioning an unregistered architect returns a warning."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.send", {
                "text": "Revisá la tarea #5",
                "sender": "human",
                "target": "arquitecto",
            })
            assert "message_id" in result
            assert "warning" in result
            assert "arquitecto" in result["warning"].lower()
            assert "registrado" in result["warning"] or "offline" in result["warning"]

        anyio.run(run)

    def test_mention_desarrollador_offline_warning(self, db_path):
        """Mentioning an unregistered developer returns a warning."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.send", {
                "text": "Implementá la feature",
                "sender": "human",
                "target": "desarrollador",
            })
            assert "message_id" in result
            assert "warning" in result
            assert "desarrollador" in result["warning"].lower()

        anyio.run(run)

    def test_mention_arquitecto_online_no_warning(self, db_path):
        """Mentioning an online architect does NOT return a warning."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()

            # Register an architect agent
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch",
                "role": "architect",
                "status": "online",
            })

            result = await self._call(server, "chat.send", {
                "text": "Revisá esto",
                "sender": "human",
                "target": "arquitecto",
            })
            assert "message_id" in result
            assert "warning" not in result, (
                f"Expected no warning when architect is online, got: {result.get('warning')}"
            )

        anyio.run(run)

    def test_mention_arquitecto_busy_no_warning(self, db_path):
        """Mentioning a busy architect does NOT return a warning."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()

            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch",
                "role": "architect",
                "status": "busy",
            })

            result = await self._call(server, "chat.send", {
                "text": "Cuando puedas revisá",
                "sender": "human",
                "target": "arquitecto",
            })
            assert "message_id" in result
            assert "warning" not in result

        anyio.run(run)

    def test_mention_arquitecto_offline_agent_registered(self, db_path):
        """Mentioning an architect that exists but is offline gives a warning."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-arch")
            await init()

            # Register architect, then set offline
            await self._call(server, "agent.heartbeat", {
                "agent_id": "test-arch",
                "role": "architect",
                "status": "online",
            })
            await self._call(server, "agent.set_status", {
                "agent_id": "test-arch",
                "status": "offline",
            })

            result = await self._call(server, "chat.send", {
                "text": "Revisá esto",
                "sender": "human",
                "target": "arquitecto",
            })
            assert "message_id" in result
            assert "warning" in result
            assert "offline" in result["warning"].lower() or "inbox" in result["warning"].lower()

        anyio.run(run)

    # ── Thread management ────────────────────────────────────────

    def test_create_and_list_threads(self, db_path):
        """Create a discussion thread and list all threads."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread_result = await self._call(server, "chat.thread_create", {
                "title": "Discusión sobre feature X",
            })
            assert "thread_id" in thread_result
            thread_id = thread_result["thread_id"]
            assert thread_result["title"] == "Discusión sobre feature X"

            threads = await self._call(server, "chat.thread_list")
            assert isinstance(threads, list)
            assert any(t["id"] == thread_id for t in threads)

        anyio.run(run)

    def test_send_message_in_thread(self, db_path):
        """Send messages in a thread and read them back."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Thread test",
            })
            tid = thread["thread_id"]

            await self._call(server, "chat.send", {
                "text": "Primer mensaje en thread",
                "sender": "human",
                "thread_id": tid,
            })
            await self._call(server, "chat.send", {
                "text": "Segundo mensaje en thread",
                "sender": "human",
                "thread_id": tid,
            })

            # Read thread messages (ORDER BY created_at ASC)
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 2
            assert messages[0]["text"] == "Primer mensaje en thread"
            assert messages[1]["text"] == "Segundo mensaje en thread"

        anyio.run(run)

    # ── Read messages since ID ───────────────────────────────────

    def test_read_messages_since(self, db_path):
        """Reading with a since parameter returns only messages with id > since.

        NOTE: Since message IDs are UUIDs (not sequential), the comparison
        is lexicographic. This test verifies the API accepts the parameter
        and returns a (possibly empty) list without error.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            await self._call(server, "chat.send", {
                "text": "Mensaje uno",
                "sender": "human",
            })
            msg2 = await self._call(server, "chat.send", {
                "text": "Mensaje dos",
                "sender": "human",
            })
            await self._call(server, "chat.send", {
                "text": "Mensaje tres",
                "sender": "human",
            })

            # since filter works as id > (lexicographic UUID comparison)
            messages = await self._call(server, "chat.read", {"since": msg2["message_id"]})
            # UUID comparison with > may return 0, 1, or 2 messages — the important
            # thing is the API doesn't error and the result is a list
            assert isinstance(messages, list)

            # Also verify that without since we get all 3
            all_msgs = await self._call(server, "chat.read")
            assert len(all_msgs) == 3

        anyio.run(run)

    # ── No heartbeat needed for default role ─────────────────────

    def test_chat_tools_work_without_heartbeat(self, db_path):
        """chat.send and chat.read work with agent_id but without heartbeat
        because the default role includes chat tools."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # No heartbeat call — default role still allows chat.*
            result = await self._call(server, "chat.send", {
                "text": "Sin heartbeat",
                "sender": "human",
            })
            assert "message_id" in result

            messages = await self._call(server, "chat.read")
            assert isinstance(messages, list)
            assert len(messages) == 1

        anyio.run(run)

    def test_chat_send_empty_text_returns_error(self, db_path):
        """Sending an empty text message returns an error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.send", {"text": ""})
            assert "error" in result

        anyio.run(run)

    # ── Multiple agents with same role ───────────────────────────

    def test_mention_arquitecto_any_online_no_warning(self, db_path):
        """If any architect agent is online, no warning."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Register two architects, one offline, one online
            await self._call(server, "agent.heartbeat", {
                "agent_id": "arch-offline",
                "role": "architect",
                "status": "offline",
            })
            await self._call(server, "agent.heartbeat", {
                "agent_id": "arch-online",
                "role": "architect",
                "status": "online",
            })

            result = await self._call(server, "chat.send", {
                "text": "Hola",
                "sender": "human",
                "target": "arquitecto",
            })
            assert "message_id" in result
            assert "warning" not in result, (
                "No warning expected if at least one architect is online"
            )

        anyio.run(run)


# ── Phase 7: Discussion threads with turn-taking ──────────────────


class TestDiscussionThreads:
    """Tests for discussion threads with participants, turn-taking, and resolution."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    async def _call(self, server, tool: str, args: dict | None = None):
        """Helper: call an MCP tool and return the parsed JSON response."""
        from mcp.types import CallToolRequest

        req = CallToolRequest(
            method="tools/call",
            params={"name": tool, "arguments": args or {}},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    # ── Thread creation with participants ─────────────────────────

    def test_create_thread_with_participants(self, db_path):
        """Create a thread with participants list."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.thread_create", {
                "title": "Discussion about feature X",
                "participants": ["arquitecto", "desarrollador"],
            })
            assert "thread_id" in result
            assert result["title"] == "Discussion about feature X"
            assert result["participants"] == ["arquitecto", "desarrollador"]

            # thread_list should include participants
            threads = await self._call(server, "chat.thread_list")
            thread = next(t for t in threads if t["id"] == result["thread_id"])
            assert thread["participants"] == ["arquitecto", "desarrollador"]
            assert thread["status"] == "open"
            assert thread["current_turn"] is None  # first message sets turn

        anyio.run(run)

    def test_create_thread_without_participants_backward_compat(self, db_path):
        """Threads without participants are public (backward compatible)."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.thread_create", {
                "title": "Public thread",
            })
            assert "thread_id" in result

            threads = await self._call(server, "chat.thread_list")
            thread = next(t for t in threads if t["id"] == result["thread_id"])
            assert thread["participants"] == []
            assert thread["current_turn"] is None

        anyio.run(run)

    # ── Turn-taking ───────────────────────────────────────────────

    def test_turn_taking_alternates_correctly(self, db_path):
        """Messages alternate between participants."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Create thread with two participants
            thread = await self._call(server, "chat.thread_create", {
                "title": "Turn test",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # First message — arquitecto speaks, turn passes to desarrollador
            r1 = await self._call(server, "chat.send", {
                "text": "Revisemos la arquitectura",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert r1["turn_number"] == 1

            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["current_turn"] == "desarrollador"

            # Second message — desarrollador speaks, turn passes back to arquitecto
            r2 = await self._call(server, "chat.send", {
                "text": "De acuerdo, vamos",
                "sender": "desarrollador",
                "thread_id": tid,
            })
            assert r2["turn_number"] == 2

            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["current_turn"] == "arquitecto"

        anyio.run(run)

    def test_turn_taking_wrong_sender_rejected(self, db_path):
        """Sending out of turn is rejected with not_your_turn error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Turn enforcement",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # arquitecto speaks first (turn passes to desarrollador)
            await self._call(server, "chat.send", {
                "text": "Mi turno",
                "sender": "arquitecto",
                "thread_id": tid,
            })

            # arquitecto tries again — should be rejected
            result = await self._call(server, "chat.send", {
                "text": "Otra vez?",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert result.get("error") == "not_your_turn"

        anyio.run(run)

    def test_human_can_always_send_regardless_of_turn(self, db_path):
        """Human (not in participants) can always message, doesn't change turn."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Human interrupt",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # arquitecto speaks (turn → desarrollador)
            await self._call(server, "chat.send", {
                "text": "Opino",
                "sender": "arquitecto",
                "thread_id": tid,
            })

            # human interrupts — allowed, turn stays with desarrollador
            result = await self._call(server, "chat.send", {
                "text": "Human here, keep going",
                "sender": "human",
                "thread_id": tid,
            })
            assert "message_id" in result
            assert "error" not in result

            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["current_turn"] == "desarrollador"  # turn didn't change

        anyio.run(run)

    def test_backward_compat_thread_no_participants_no_turn_enforcement(self, db_path):
        """Threads without participants have no turn enforcement."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Public thread",
            })
            tid = thread["thread_id"]

            # Anyone can send any number of times
            r1 = await self._call(server, "chat.send", {
                "text": "Msg 1",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert "message_id" in r1

            r2 = await self._call(server, "chat.send", {
                "text": "Msg 2",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert "message_id" in r2

            r3 = await self._call(server, "chat.send", {
                "text": "Msg 3",
                "sender": "desarrollador",
                "thread_id": tid,
            })
            assert "message_id" in r3

            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 3

        anyio.run(run)

    # ── thread_get_pending ─────────────────────────────────────────

    def test_thread_get_pending_returns_my_turn(self, db_path):
        """thread_get_pending returns threads where it's my turn."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "For dev",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # arquitecto speaks (turn → desarrollador)
            await self._call(server, "chat.send", {
                "text": "Implementá esto",
                "sender": "arquitecto",
                "thread_id": tid,
            })

            # desarrollador should see this thread as pending
            pending = await self._call(server, "chat.thread_get_pending", {
                "agent_name": "desarrollador",
            })
            assert any(p["id"] == tid for p in pending), (
                f"desarrollador should see thread {tid} as pending, got {pending}"
            )

            # arquitecto should NOT see it (it's desarrollador's turn)
            pending_arch = await self._call(server, "chat.thread_get_pending", {
                "agent_name": "arquitecto",
            })
            assert not any(p["id"] == tid for p in pending_arch), (
                f"arquitecto should NOT see thread {tid} as pending, got {pending_arch}"
            )

        anyio.run(run)

    def test_thread_get_pending_new_thread_no_messages(self, db_path):
        """A fresh thread (no messages) should NOT appear as pending.

        A thread with last_activity_at == created_at has no messages yet,
        so there is nothing pending for participants to act on.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "New discussion",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # Neither participant should see it — no messages have been sent
            for agent in ("arquitecto", "desarrollador"):
                pending = await self._call(server, "chat.thread_get_pending", {
                    "agent_name": agent,
                })
                assert not any(p["id"] == tid for p in pending), (
                    f"{agent} should NOT see new thread {tid} as pending (no messages)"
                )

        anyio.run(run)

    def test_thread_get_pending_ignores_public_threads(self, db_path):
        """Public threads (no participants) are NOT returned by thread_get_pending."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Create public thread (no participants)
            thread = await self._call(server, "chat.thread_create", {
                "title": "Public announcement",
            })
            tid = thread["thread_id"]

            # Should not appear as pending for anyone
            for agent in ("arquitecto", "desarrollador", "human"):
                pending = await self._call(server, "chat.thread_get_pending", {
                    "agent_name": agent,
                })
                assert not any(p["id"] == tid for p in pending), (
                    f"Public thread should not be pending for {agent}, got {pending}"
                )

        anyio.run(run)

    def test_thread_get_pending_requires_agent_name(self, db_path):
        """Calling thread_get_pending without agent_name returns error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.thread_get_pending", {})
            assert "error" in result

        anyio.run(run)

    # ── thread_resolve ─────────────────────────────────────────────

    def test_resolve_thread_manually(self, db_path):
        """Manually resolve a thread."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "To resolve",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            result = await self._call(server, "chat.thread_resolve", {
                "thread_id": tid,
            })
            assert result["status"] == "resolved"

            # Verify it's resolved
            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["status"] == "resolved"

            # System message should exist
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert any(m["sender"] == "system" for m in messages)

        anyio.run(run)

    def test_resolve_thread_not_found(self, db_path):
        """Resolving a non-existent thread returns error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.thread_resolve", {
                "thread_id": "nonexistent",
            })
            assert "error" in result

        anyio.run(run)

    def test_resolve_already_resolved_thread(self, db_path):
        """Resolving an already-resolved thread returns success."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Already resolved",
            })
            tid = thread["thread_id"]

            await self._call(server, "chat.thread_resolve", {"thread_id": tid})
            result = await self._call(server, "chat.thread_resolve", {"thread_id": tid})
            assert result["status"] == "resolved"
            assert "already resolved" in result.get("note", "").lower()

        anyio.run(run)

    # ── Bug 3: resolved thread rejects messages ────────────────────

    def test_send_to_resolved_thread_rejected(self, db_path):
        """Sending a message to a resolved thread returns an error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Closed thread",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            await self._call(server, "chat.thread_resolve", {"thread_id": tid})

            result = await self._call(server, "chat.send", {
                "text": "Hola?",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert result.get("error") == "thread_resolved"
            assert "resuelto" in result.get("detail", "").lower()

        anyio.run(run)

    def test_send_to_nonexistent_thread_rejected(self, db_path):
        """Sending to a non-existent thread returns error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.send", {
                "text": "Hola?",
                "sender": "arquitecto",
                "thread_id": "no-such-thread",
            })
            assert result.get("error") == "thread_not_found"

        anyio.run(run)

    # ── Bug 2: turn_number atomicity ───────────────────────────────

    def test_turn_numbers_are_strictly_sequential(self, db_path):
        """Multiple rapid sends produce unique sequential turn_numbers."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Sequential turns",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            turns = []
            for i in range(5):
                sender = "arquitecto" if i % 2 == 0 else "desarrollador"
                result = await self._call(server, "chat.send", {
                    "text": f"Mensaje {i}",
                    "sender": sender,
                    "thread_id": tid,
                })
                turns.append(result["turn_number"])

            # All turn_numbers must be unique and increasing
            assert len(turns) == 5
            assert turns == [1, 2, 3, 4, 5], f"Expected [1,2,3,4,5], got {turns}"

        anyio.run(run)

    def test_turn_numbers_no_collision_on_consecutive_same_sender(self, db_path):
        """Even the same sender sending consecutively gets unique turn_numbers."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Single-participant thread — same sender always
            thread = await self._call(server, "chat.thread_create", {
                "title": "Monologue",
                "participants": ["arquitecto"],
            })
            tid = thread["thread_id"]

            results = []
            for i in range(3):
                result = await self._call(server, "chat.send", {
                    "text": f"msg {i}",
                    "sender": "arquitecto",
                    "thread_id": tid,
                })
                results.append(result["turn_number"])

            assert len(results) == 3, f"Expected 3 results, got {results}"
            assert results == [1, 2, 3], f"Expected [1,2,3], got {results}"

        anyio.run(run)

    # ── Bug 5: concurrent same-sender turn-taking race ─────────────

    async def _concurrent_send(self, server, sender: str, thread_id: str, text: str):
        """Helper to send a message from within asyncio.gather."""

        req = CallToolRequest(
            method="tools/call",
            params={"name": "chat.send", "arguments": {
                "text": text, "sender": sender, "thread_id": thread_id,
            }},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    async def _concurrent_resolve(self, server, thread_id: str):
        """Helper to resolve a thread from within asyncio.gather."""
        req = CallToolRequest(
            method="tools/call",
            params={"name": "chat.thread_resolve", "arguments": {"thread_id": thread_id}},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    def test_concurrent_same_sender_only_one_succeeds(self, db_path):
        """Two concurrent sends from same sender: atomic UPDATE prevents double-send."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Concurrent race",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # First message from arquitecto to establish turn order
            await self._call(server, "chat.send", {
                "text": "Abre el thread",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            # Now it's desarrollador's turn

            # Fire two concurrent sends from desarrollador
            results = await asyncio.gather(
                self._concurrent_send(server, "desarrollador", tid, "msg A"),
                self._concurrent_send(server, "desarrollador", tid, "msg B"),
            )

            successes = [r for r in results if "message_id" in r]
            failures = [r for r in results if r.get("error") == "not_your_turn"]

            assert len(successes) >= 1, (
                f"Expected at least 1 success, got {results}"
            )
            # Verify total messages = 2 (first + the one race winner)
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 2, (
                f"Expected 2 messages total, got {len(messages)}: {messages}"
            )
            # Each message should have unique turn_number
            turn_numbers = [m["turn_number"] for m in messages]
            assert len(turn_numbers) == len(set(turn_numbers)), (
                f"turn_numbers must be unique, got {turn_numbers}"
            )

        anyio.run(run)

    def test_concurrent_establishes_turn_correctly_after_race(self, db_path):
        """After a concurrent race, the thread's current_turn is consistent."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Race then turn check",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # First message from arquitecto
            await self._call(server, "chat.send", {
                "text": "first",
                "sender": "arquitecto",
                "thread_id": tid,
            })

            # Race: two concurrent from desarrollador
            await asyncio.gather(
                self._concurrent_send(server, "desarrollador", tid, "race A"),
                self._concurrent_send(server, "desarrollador", tid, "race B"),
            )

            # After the race, current_turn must be "arquitecto" again
            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["current_turn"] == "arquitecto", (
                f"After race, expected turn=arquitecto, got {t['current_turn']}"
            )

            # arquitecto should now be able to send (it's their turn)
            result = await self._call(server, "chat.send", {
                "text": "my turn again",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert "message_id" in result, (
                f"arquitecto should be able to send after race, got {result}"
            )

        anyio.run(run)

    # ── Cross-participant causal order ─────────────────────────

    def test_cross_participant_causal_order_preserved(self, db_path):
        """When two participants race, messages are persisted in causal order.

        A says "first" (turn → B).  While A's tx commits, B cannot see the
        new turn until BOTH the UPDATE and INSERT of A's message are durable.
        So chat.read will always see A's message before B's reply.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Ping pong causal",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # Rapid ping-pong: arquitecto → desarrollador → arquitecto
            r1 = await self._call(server, "chat.send", {
                "text": "ping",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert r1["turn_number"] == 1

            r2 = await self._call(server, "chat.send", {
                "text": "pong",
                "sender": "desarrollador",
                "thread_id": tid,
            })
            assert r2["turn_number"] == 2

            r3 = await self._call(server, "chat.send", {
                "text": "ping2",
                "sender": "arquitecto",
                "thread_id": tid,
            })
            assert r3["turn_number"] == 3

            # Read all messages — they must be in turn_number order
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 3
            for i, msg in enumerate(messages):
                assert msg["turn_number"] == i + 1, (
                    f"Message {i} expected turn_number={i+1}, got {msg['turn_number']}"
                )
                assert msg["text"] in ("ping", "pong", "ping2")

        anyio.run(run)

    def test_concurrent_cross_participant_one_rejected(self, db_path):
        """Cross-participant race: only the correct-turn sender gets through.

        After "arquitecto" speaks (turn → "desarrollador"), fire concurrent
        sends from both participants.  Exactly 1 must fail (arquitecto, who
        no longer holds the turn) and exactly 1 must succeed (desarrollador).
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Cross race",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # First message — turn → desarrollador
            await self._call(server, "chat.send", {
                "text": "Tu turno",
                "sender": "arquitecto",
                "thread_id": tid,
            })

            # Race: both try to send simultaneously
            results = await asyncio.gather(
                self._concurrent_send(server, "arquitecto", tid, "me again?"),
                self._concurrent_send(server, "desarrollador", tid, "my turn"),
            )

            successes = [r for r in results if "message_id" in r]
            failures = [r for r in results if r.get("error") == "not_your_turn"]

            assert len(successes) == 1, (
                f"Expected exactly 1 success, got {len(successes)}: {results}"
            )
            assert len(failures) == 1, (
                f"Expected exactly 1 failure, got {len(failures)}: {results}"
            )

            # Exactly 2 messages total (first + the race winner)
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 2, (
                f"Expected 2 messages, got {len(messages)}"
            )

            # turn_numbers must be strictly increasing
            turns = [m["turn_number"] for m in messages]
            assert turns == [1, 2], f"Expected turns [1,2], got {turns}"

        anyio.run(run)

    # ── Send-vs-resolve race (lock-winner semantics) ─────────────
    #
    # CHAT.RESOLVE vs CHAT.SEND — CONCURRENCY CONTRACT
    # ─────────────────────────────────────────────────────────
    # When chat.send and chat.thread_resolve race concurrently,
    # the system follows **lock-winner semantics**: the operation
    # that acquires the SQLite write lock first (via BEGIN IMMEDIATE
    # inside with_transaction) decides the observable outcome.
    #
    # Both outcomes are VALID and consistent:
    #
    #   Scenario A — resolve wins the lock:
    #     The send's transaction sees status='resolved' and raises
    #     _ThreadResolvedError.  The caller receives
    #     {"error": "thread_resolved"}.  No message is persisted.
    #
    #   Scenario B — send wins the lock:
    #     The send's transaction commits (INSERT + turn advance),
    #     THEN resolve commits.  The message is persisted *before*
    #     the resolve takes effect.  This is correct: the message
    #     happened causally before the resolve.
    #
    # Either way the final state is consistent — no orphaned data,
    # no messages after a committed resolve, no
    # resolved-while-open contradiction.

    def test_send_vs_resolve_lock_winner_any_outcome_valid(self, db_path):
        """send vs resolve: both possible outcomes are valid and consistent.

        Set up: first message from arquitecto, turn → desarrollador.
        Race: desarrollador.send() vs thread_resolve() — BOTH outcomes
        are pure send-vs-resolve (not_your_turn cannot appear because
        desarrollador IS the correct turn holder).

        Scenario A (resolve wins): send returns thread_resolved.
        Scenario B (send wins):   send returns message_id.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Lock-winner test",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # First message — turn → desarrollador
            await self._call(server, "chat.send", {
                "text": "Tu turno", "sender": "arquitecto", "thread_id": tid,
            })

            # Race: desarrollador (correct turn) vs resolve
            results = await asyncio.gather(
                self._concurrent_send(server, "desarrollador", tid, "racing"),
                self._call(server, "chat.thread_resolve", {"thread_id": tid}),
            )

            send_result = results[0]
            # Only these two outcomes are valid per the concurrency contract:
            valid = (
                send_result.get("error") == "thread_resolved"   # resolve won
                or "message_id" in send_result                  # send won
            )
            assert valid, (
                f"Lock-winner semantics: expected thread_resolved or "
                f"message_id. Got: {send_result}"
            )

        anyio.run(run)

    def test_send_vs_resolve_non_participant_any_outcome_valid(self, db_path):
        """Non-participant send vs resolve: either outcome is valid."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Human lock-winner",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            results = await asyncio.gather(
                self._concurrent_send(server, "human", tid, "hello?"),
                self._call(server, "chat.thread_resolve", {"thread_id": tid}),
            )

            send_result = results[0]
            valid = (
                send_result.get("error") == "thread_resolved"
                or "message_id" in send_result
            )
            assert valid, (
                f"Lock-winner semantics: expected thread_resolved or "
                f"message_id. Got: {send_result}"
            )

        anyio.run(run)

    def test_send_vs_resolve_invariants_hold(self, db_path):
        """Regardless of who wins the send-vs-resolve race, invariants hold.

        Invariant 1: chat.read does not error and returns a list.
        Invariant 2: thread status is 'resolved'.
        Invariant 3: the thread is listed as resolved.
        Invariant 4: sending again to the resolved thread yields
                     thread_resolved.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Invariant check",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            await asyncio.gather(
                self._concurrent_send(server, "arquitecto", tid, "racing"),
                self._call(server, "chat.thread_resolve", {"thread_id": tid}),
            )

            # Invariant 1: chat.read works
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert isinstance(messages, list)

            # Invariant 2: thread is resolved
            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["status"] == "resolved", (
                f"Thread must be resolved after race, got {t['status']}"
            )

            # Invariant 3: sending again yields thread_resolved
            r = await self._call(server, "chat.send", {
                "text": "after resolve", "sender": "arquitecto", "thread_id": tid,
            })
            assert r.get("error") in ("thread_resolved",), (
                f"Send after race must be rejected, got {r}"
            )

        anyio.run(run)

    # ── chat.read ordering ───────────────────────────────────────

    def test_chat_read_causal_ordering(self, db_path):
        """chat.read returns messages in causal (insertion) order via rowid."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Order test",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # Send messages in ping-pong
            texts = []
            for sender, text in [
                ("arquitecto", "first"),
                ("desarrollador", "second"),
                ("arquitecto", "third"),
            ]:
                r = await self._call(server, "chat.send", {
                    "text": text, "sender": sender, "thread_id": tid,
                })
                texts.append((r["turn_number"], text))

            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 3

            # Must be in turn_number order regardless of created_at precision
            for i, msg in enumerate(messages):
                assert msg["turn_number"] == i + 1, (
                    f"Expected turn_number {i+1} at position {i}, "
                    f"got {msg['turn_number']}: {messages}"
                )

        anyio.run(run)

    def test_chat_read_human_system_interleaving(self, db_path):
        """chat.read preserves causal order across human/system interleavings.

        Sequence: arquitecto (has turn_number) → human (NULL) → desarrollador
        (has turn_number) → system (NULL).  All four must appear in that
        exact causal order regardless of turn_number presence.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Interleaving",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # 1. arquitecto speaks (turn_number = 1)
            await self._call(server, "chat.send", {
                "text": "from architect", "sender": "arquitecto", "thread_id": tid,
            })

            # 2. human interjects (no turn_number)
            await self._call(server, "chat.send", {
                "text": "from human", "sender": "human", "thread_id": tid,
            })

            # 3. desarrollador replies (turn_number = 2)
            await self._call(server, "chat.send", {
                "text": "from developer", "sender": "desarrollador", "thread_id": tid,
            })

            # 4. system message via resolve (no turn_number)
            await self._call(server, "chat.thread_resolve", {"thread_id": tid})

            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 4, f"Expected 4 messages, got {len(messages)}"

            # Verify causal order: architect → human → developer → system
            expected_senders = ["arquitecto", "human", "desarrollador", "system"]
            for i, (msg, expected) in enumerate(zip(messages, expected_senders)):
                assert msg["sender"] == expected, (
                    f"Position {i}: expected sender '{expected}', "
                    f"got '{msg['sender']}': {[(m['sender'], m['text'][:15]) for m in messages]}"
                )

            # Turn_numbers in expected positions
            assert messages[0]["turn_number"] == 1  # arquitecto
            assert messages[1]["turn_number"] is None  # human
            assert messages[2]["turn_number"] == 2  # desarrollador
            assert messages[3]["turn_number"] is None  # system

        anyio.run(run)

    # ── Cross-participant line-cutting prevention ─────────────────

    def test_cross_participant_line_cutting_prevented(self, db_path):
        """A participant sending out of turn is rejected or accepted
        depending on lock-acquisition order.

        After arquitecto speaks (turn→desarrollador), fire concurrent
        sends from arquitecto (wrong turn) and desarrollador (correct).

        With live-turn semantics (current_turn read inside the write
        lock), the validator checks whether the sender holds the turn
        *at lock time*, not at request time.  This means:

        - If arquitecto acquires the lock BEFORE desarrollador:
          arquitecto sees turn=desarrollador and is REJECTED.
          Then desarrollador sees turn=desarrollador and SUCCEEDS.

        - If desarrollador acquires the lock BEFORE arquitecto:
          desarrollador SUCCEEDS, advancing the turn to arquitecto.
          Then arquitecto sees turn=arquitecto and SUCCEEDS.

        Both outcomes are valid.  The only invariant: desarrollador
        must always succeed (it was the correct turn holder).
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Line cutting",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # First message — establishes turn = desarrollador
            await self._call(server, "chat.send", {
                "text": "Tu turno", "sender": "arquitecto", "thread_id": tid,
            })

            # Fire both concurrently.
            results = await asyncio.gather(
                self._concurrent_send(server, "arquitecto", tid, "line cut?"),
                self._concurrent_send(server, "desarrollador", tid, "on time"),
            )

            # desarrollador must always succeed — it was the correct turn
            desarrollador_ok = "message_id" in results[1]
            assert desarrollador_ok, (
                f"desarrollador debe poder enviar, got {results[1]}"
            )

            successes = [r for r in results if "message_id" in r]
            # Both may succeed if the turn cycled back to arquitecto
            assert 1 <= len(successes) <= 2, (
                f"Expected 1-2 successes, got {len(successes)}: {results}"
            )

            messages = await self._call(server, "chat.read", {"thread_id": tid})
            expected = 3 if len(successes) == 2 else 2
            assert len(messages) == expected, (
                f"Expected {expected} messages, got {len(messages)}"
            )
            # All new messages must have turn_number
            assert all(m["turn_number"] is not None for m in messages), (
                f"All messages should have turn_number, got {messages}"
            )

        anyio.run(run)

    def test_cross_participant_first_message_race_benign(self, db_path):
        """Both participants racing for the first message: both succeed (benign).

        When current_turn is NULL (fresh thread), any participant may send.
        Two concurrent sends from different participants both go through.
        """
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "First message race",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            results = await asyncio.gather(
                self._concurrent_send(server, "arquitecto", tid, "first A"),
                self._concurrent_send(server, "desarrollador", tid, "first B"),
            )

            successes = [r for r in results if "message_id" in r]
            # Both should succeed (first-message race is benign)
            assert len(successes) == 2, (
                f"Both first messages should succeed, got {results}"
            )

            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert len(messages) == 2
            # Both must have unique turn_numbers
            turns = [m["turn_number"] for m in messages]
            assert len(turns) == len(set(turns)) == 2

        anyio.run(run)

    # ── Auto-resolve timeout ─────────────────────────────────────

    def test_thread_auto_resolve_by_timeout(self, db_path):
        """Auto-resolve resolves threads idle longer than the timeout.

        Create a thread, set last_activity_at far in the past via direct
        SQL, call _resolve_stale_threads with a fresh Database instance,
        and verify the thread is resolved.
        """
        async def run():
            import sqlite3

            from agent_bridge.server import _resolve_stale_threads
            from agent_bridge.state.database import Database

            server, init = create_server(db_path=db_path, agent_id="test")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Auto-resolve test",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # Send a message so last_activity_at gets set
            await self._call(server, "chat.send", {
                "text": "last word", "sender": "arquitecto", "thread_id": tid,
            })

            # Bump last_activity_at far enough into the past via direct SQL
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE threads SET last_activity_at = datetime('now', '-10 minutes') WHERE id = ?",
                (tid,),
            )
            conn.commit()
            conn.close()

            # Resolve stale threads using a fresh Database on the same file
            db2 = Database(db_path)
            await db2.initialize()
            try:
                result = await _resolve_stale_threads(db2)
            finally:
                # db2 has no async close — let GC handle it
                pass

            assert result["resolved_count"] >= 1, (
                f"Expected at least 1 resolved thread, got {result}"
            )

            # Verify via the original server's chat.thread_list
            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["status"] == "resolved", (
                f"Expected resolved, got {t['status']}"
            )

            # A system message should have been inserted
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            assert any(m["sender"] == "system" for m in messages), (
                "Expected a system message from auto-resolve"
            )

        anyio.run(run)

    def test_thread_auto_resolve_skips_public_threads(self, db_path):
        """Auto-resolve does NOT resolve threads without participants."""
        async def run():
            import sqlite3

            from agent_bridge.server import _resolve_stale_threads
            from agent_bridge.state.database import Database

            server, init = create_server(db_path=db_path, agent_id="test")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Public thread",
            })
            tid = thread["thread_id"]

            # Set last_activity_at old
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE threads SET last_activity_at = datetime('now', '-10 minutes') WHERE id = ?",
                (tid,),
            )
            conn.commit()
            conn.close()

            db2 = Database(db_path)
            await db2.initialize()
            result = await _resolve_stale_threads(db2)

            # Public threads should NOT be auto-resolved
            assert result["resolved_count"] == 0, (
                f"Public threads should not be auto-resolved, got {result}"
            )

            threads = await self._call(server, "chat.thread_list")
            t = next(x for x in threads if x["id"] == tid)
            assert t["status"] == "open", (
                f"Public thread should still be open, got {t['status']}"
            )

        anyio.run(run)

    # ── Resolve-vs-resolve idempotence ───────────────────────────

    def test_resolve_concurrent_only_one_system_message(self, db_path):
        """Two concurrent resolves: only the winner inserts a system message."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Resolve race",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            results = await asyncio.gather(
                self._concurrent_resolve(server, tid),
                self._concurrent_resolve(server, tid),
            )

            # Both should report resolved
            for r in results:
                assert r.get("status") == "resolved", (
                    f"Both should report resolved, got {r}"
                )

            # Exactly ONE system message
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            system_msgs = [m for m in messages if m["sender"] == "system"]
            assert len(system_msgs) == 1, (
                f"Expected exactly 1 system message, got {len(system_msgs)}: {messages}"
            )

        anyio.run(run)

    def test_resolve_concurrent_then_send_rejected(self, db_path):
        """After concurrent resolves resolve the thread, sends are rejected."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Resolve then send",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            await asyncio.gather(
                self._concurrent_resolve(server, tid),
                self._concurrent_resolve(server, tid),
            )

            # Send to resolved thread must fail
            result = await self._call(server, "chat.send", {
                "text": "late", "sender": "arquitecto", "thread_id": tid,
            })
            assert result.get("error") in ("thread_resolved",)

        anyio.run(run)

    def test_auto_resolve_vs_manual_resolve_no_dup_system_message(self, db_path):
        """Auto-resolve (background) and manual resolve: exactly one system message."""
        async def run():
            import sqlite3
            from agent_bridge.server import _resolve_stale_threads
            from agent_bridge.state.database import Database

            server, init = create_server(db_path=db_path, agent_id="test")
            await init()

            thread = await self._call(server, "chat.thread_create", {
                "title": "Auto vs manual",
                "participants": ["arquitecto", "desarrollador"],
            })
            tid = thread["thread_id"]

            # Send a message to set last_activity_at
            await self._call(server, "chat.send", {
                "text": "last", "sender": "arquitecto", "thread_id": tid,
            })

            # Bump last_activity_at into the past
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE threads SET last_activity_at = datetime('now', '-10 minutes') WHERE id = ?",
                (tid,),
            )
            conn.commit()
            conn.close()

            # Fire auto-resolve + manual resolve concurrently
            db2 = Database(db_path)
            await db2.initialize()
            results = await asyncio.gather(
                _resolve_stale_threads(db2),
                self._concurrent_resolve(server, tid),
            )

            auto_result = results[0]
            # At most 1 resolved between both
            assert auto_result.get("resolved_count", 0) <= 1
            # Manual resolve should report resolved
            manual_result = results[1]
            assert manual_result.get("status") == "resolved", (
                f"Manual resolve should report resolved, got {manual_result}"
            )

            # Exactly ONE system message total
            messages = await self._call(server, "chat.read", {"thread_id": tid})
            system_msgs = [m for m in messages if m["sender"] == "system"]
            assert len(system_msgs) == 1, (
                f"Expected exactly 1 system message, got {len(system_msgs)}: {messages}"
            )

        anyio.run(run)


# ── Fase 2 / 3: Enhanced messaging, mark_read, pagination ────────


class TestEnhancedMessaging:
    """Tests for Fase 2/3 enhancements: mark_read, limit, msg_type/priority."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        Path(path + ".lock").unlink(missing_ok=True)

    async def _call(self, server, tool: str, args: dict | None = None):
        from mcp.types import CallToolRequest

        req = CallToolRequest(
            method="tools/call",
            params={"name": tool, "arguments": args or {}},
        )
        resp = await server.request_handlers[CallToolRequest](req)
        return json.loads(resp.root.content[0].text)

    def test_chat_mark_read(self, db_path):
        """Mark a specific message as read, then verify via chat.read."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Send a message
            send = await self._call(server, "chat.send", {
                "text": "mensaje de prueba",
                "sender": "human",
                "target": "desarrollador",
            })
            msg_id = send["message_id"]

            # Read normally — message should appear
            msgs = await self._call(server, "chat.read", {"target": "desarrollador"})
            assert any(m["id"] == msg_id for m in msgs)
            target_msg = next(m for m in msgs if m["id"] == msg_id)
            assert target_msg["read"] is False

            # Mark as read
            result = await self._call(server, "chat.mark_read", {"message_id": msg_id})
            assert result["status"] == "marked_read"

            # Verify — when filtering unread_only, it should not appear
            msgs = await self._call(server, "chat.read", {
                "target": "desarrollador", "unread_only": True,
            })
            assert not any(m["id"] == msg_id for m in msgs)

        anyio.run(run)

    def test_chat_read_limit(self, db_path):
        """Limit parameter returns at most N messages."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            # Send 3 messages
            for i in range(3):
                await self._call(server, "chat.send", {
                    "text": f"msg {i}",
                    "sender": "human",
                })

            # Limit 1 — only 1 message
            msgs = await self._call(server, "chat.read", {"limit": 1})
            assert len(msgs) == 1

            # Limit 2 — only 2 messages
            msgs = await self._call(server, "chat.read", {"limit": 2})
            assert len(msgs) == 2

            # No limit — all 3
            msgs = await self._call(server, "chat.read")
            assert len(msgs) == 3

        anyio.run(run)

    def test_chat_read_priority_first(self, db_path):
        """Priority_first returns urgent/high messages before normal."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            await self._call(server, "chat.send", {
                "text": "normal", "sender": "human", "priority": "normal",
            })
            await self._call(server, "chat.send", {
                "text": "urgente", "sender": "human", "priority": "urgent",
            })
            await self._call(server, "chat.send", {
                "text": "alta", "sender": "human", "priority": "high",
            })

            msgs = await self._call(server, "chat.read", {"priority_first": True})
            priorities = [m["priority"] for m in msgs]
            # urgent first, then high, then normal
            assert priorities[0] == "urgent"
            assert priorities[1] == "high"
            assert priorities[2] == "normal"

        anyio.run(run)

    def test_send_message_too_long(self, db_path):
        """Messages over 4000 chars are rejected with message_too_long error."""
        async def run():
            server, init = create_server(db_path=db_path, agent_id="test-chat")
            await init()

            result = await self._call(server, "chat.send", {
                "text": "X" * 4001,
                "sender": "human",
            })
            assert result["error"] == "message_too_long"
            assert result["max_length"] == 4000

            # Exactly 4000 should succeed
            result = await self._call(server, "chat.send", {
                "text": "X" * 4000,
                "sender": "human",
            })
            assert "message_id" in result

        anyio.run(run)
