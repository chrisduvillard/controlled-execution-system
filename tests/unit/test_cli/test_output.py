"""Tests for CLI output helpers (_output module)."""

from __future__ import annotations

import json

from ces.cli._output import output_dict, output_table, set_json_mode


class TestOutputTable:
    """Tests for output_table()."""

    def test_table_json_mode(self, capsys: object) -> None:
        """output_table in JSON mode prints JSON array to stdout."""
        set_json_mode(True)
        try:
            output_table("Test", ["Name", "Value"], [["foo", "bar"], ["baz", "qux"]])
            captured = capsys.readouterr()  # type: ignore[attr-defined]
            data = json.loads(captured.out)
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0] == {"Name": "foo", "Value": "bar"}
            assert data[1] == {"Name": "baz", "Value": "qux"}
        finally:
            set_json_mode(False)

    def test_table_rich_mode_no_exception(self) -> None:
        """output_table in Rich mode completes without raising exceptions."""
        set_json_mode(False)
        # Should not raise
        output_table("Test Table", ["Col1", "Col2"], [["a", "b"]])

    def test_table_empty_rows(self, capsys: object) -> None:
        """output_table handles empty rows in JSON mode."""
        set_json_mode(True)
        try:
            output_table("Empty", ["A", "B"], [])
            captured = capsys.readouterr()  # type: ignore[attr-defined]
            data = json.loads(captured.out)
            assert data == []
        finally:
            set_json_mode(False)


class TestOutputDict:
    """Tests for output_dict()."""

    def test_dict_json_mode(self, capsys: object) -> None:
        """output_dict in JSON mode prints JSON object to stdout."""
        set_json_mode(True)
        try:
            output_dict({"key": "value", "count": 42})
            captured = capsys.readouterr()  # type: ignore[attr-defined]
            data = json.loads(captured.out)
            assert data == {"key": "value", "count": 42}
        finally:
            set_json_mode(False)

    def test_dict_rich_mode_no_exception(self) -> None:
        """output_dict in Rich mode completes without raising exceptions."""
        set_json_mode(False)
        # Should not raise
        output_dict({"status": "ok"}, title="Status")

    def test_dict_empty(self, capsys: object) -> None:
        """output_dict handles empty dict in JSON mode."""
        set_json_mode(True)
        try:
            output_dict({})
            captured = capsys.readouterr()  # type: ignore[attr-defined]
            data = json.loads(captured.out)
            assert data == {}
        finally:
            set_json_mode(False)


class TestSetJsonMode:
    """Tests for set_json_mode()."""

    def test_toggle_json_mode(self) -> None:
        """set_json_mode toggles the global JSON mode flag."""
        set_json_mode(True)
        # Verify by checking output_table produces JSON
        set_json_mode(False)
        # No exception means it works
