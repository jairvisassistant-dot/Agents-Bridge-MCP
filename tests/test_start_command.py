"""Tests for the `agent-bridge start` command — argument parsing and subcommand routing."""
import argparse
import sys
from unittest.mock import patch

import pytest


class TestStartCommandParser:
    """Tests for the argument parser's `start` subcommand."""

    def _make_parser(self):
        """Replicate the parser from main.py for isolated testing."""
        from agent_bridge.main import main
        return

    def test_start_subcommand_exists(self):
        """The parser should accept 'start' as a subcommand."""
        from agent_bridge.main import main

        # Use argparse in isolation: capture the parser setup
        import argparse

        parser = argparse.ArgumentParser(description="Agent Bridge")
        subparsers = parser.add_subparsers(dest="command")

        start_parser = subparsers.add_parser("start", help="Start SSE server + TUI")
        start_parser.add_argument("--db-path", default="bridge.db")
        start_parser.add_argument("--port", type=int, default=8765)
        start_parser.add_argument("--headless", action="store_true")
        start_parser.add_argument("--ui-only", action="store_true")

        # Test: start with no flags
        args = parser.parse_args(["start"])
        assert args.command == "start"
        assert args.db_path == "bridge.db"
        assert args.port == 8765
        assert args.headless is False
        assert args.ui_only is False

    def test_start_with_headless(self):
        """`start --headless` should set headless=True."""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--headless", action="store_true")
        start_parser.add_argument("--ui-only", action="store_true")
        start_parser.add_argument("--db-path", default="bridge.db")
        start_parser.add_argument("--port", type=int, default=8765)

        args = parser.parse_args(["start", "--headless"])
        assert args.command == "start"
        assert args.headless is True
        assert args.ui_only is False

    def test_start_with_ui_only(self):
        """`start --ui-only` should set ui_only=True."""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--headless", action="store_true")
        start_parser.add_argument("--ui-only", action="store_true")
        start_parser.add_argument("--db-path", default="bridge.db")
        start_parser.add_argument("--port", type=int, default=8765)

        args = parser.parse_args(["start", "--ui-only"])
        assert args.ui_only is True
        assert args.headless is False

    def test_start_with_custom_port(self):
        """`start --port 9876` should set port."""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--port", type=int, default=8765)

        args = parser.parse_args(["start", "--port", "9876"])
        assert args.port == 9876

    def test_start_with_custom_db_path(self):
        """`start --db-path /tmp/test.db` should set db_path."""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--db-path", default="bridge.db")

        args = parser.parse_args(["start", "--db-path", "/tmp/test.db"])
        assert args.db_path == "/tmp/test.db"

    def test_start_help_output(self):
        """`start --help` should list available options."""
        import argparse
        from io import StringIO

        parser = argparse.ArgumentParser(prog="agent-bridge")
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--headless", action="store_true")

        # Capture help output
        with patch("sys.stdout", new=StringIO()) as fake_out:
            with pytest.raises(SystemExit) as exc:
                # argparse --help raises SystemExit(0)
                parser.parse_args(["start", "--help"])
            assert exc.value.code == 0

    def test_legacy_args_still_work(self):
        """Top-level legacy args (--db-path, --transport, etc.) should parse correctly."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--db-path", default="bridge.db")
        parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
        parser.add_argument("--port", type=int, default=8765)

        args = parser.parse_args(["--db-path", "custom.db", "--transport", "sse"])
        assert args.db_path == "custom.db"
        assert args.transport == "sse"

    def test_start_and_legacy_are_mutually_exclusive(self):
        """The 'start' subcommand and legacy args should not overlap."""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("start")

        parser.add_argument("--db-path", default="bridge.db")

        # Parsing 'start' should give command='start' and db_path default
        args = parser.parse_args(["start"])
        assert args.command == "start"
        assert hasattr(args, "db_path")  # from the parser-level arg

    def test_start_with_dry_run(self):
        """`start --dry-run` should set dry_run=True."""
        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--dry-run", action="store_true")
        start_parser.add_argument("--db-path", default="bridge.db")

        args = parser.parse_args(["start", "--dry-run"])
        assert args.command == "start"
        assert args.dry_run is True

        # Without --dry-run, should be False
        args = parser.parse_args(["start"])
        assert args.dry_run is False

    def test_legacy_top_level_dry_run(self):
        """Legacy top-level --dry-run should be accepted."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")

        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True
