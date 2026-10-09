import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from KiPartClient.Misc import ActionType
from KiPartClient.ChangeReview import (
    resolve_action, iter_change_rows, mark_take_server, write_decisions, default_decision,
)
from KiPartClient.RestAPI import _format_in_use


def test_default_conflict_is_ignore_and_other_changes_apply():
    assert default_decision({"type": ActionType.Conflict}) == "ignore"
    assert default_decision({"type": ActionType.UpdateRemote}) == "apply"


def test_resolve_keeps_current_behavior_when_decision_is_unset():
    conflict = {"type": ActionType.Conflict, "file": "A"}
    assert resolve_action(conflict) is conflict
    download = {"type": ActionType.Download, "file": "A"}
    assert resolve_action(download) is download


def test_ignore_skips_and_revert_flips_direction():
    assert resolve_action({"type": ActionType.Upload, "file": "A", "decision": "ignore"}) is None

    reverted = resolve_action({
        "type": ActionType.UpdateRemote,
        "file": "A",
        "expected_hash": "server",
        "decision": "revert",
    })
    assert reverted["type"] == ActionType.UpdateLocal
    assert reverted["file_hash"] == "server"

    undone_download = resolve_action({
        "type": ActionType.Download,
        "file": "A",
        "uuid": "u",
        "file_hash": "abc",
        "decision": "revert",
    })
    assert undone_download["type"] == ActionType.DeleteRemote
    assert undone_download["expected_hash"] == "abc"


def test_conflict_apply_uploads_and_revert_takes_server():
    conflict = {
        "type": ActionType.Conflict,
        "file": "A",
        "uuid": "u",
        "id": 3,
        "server_hash": "srv",
        "local_hash": "loc",
    }
    uploaded = resolve_action({**conflict, "decision": "apply"})
    assert uploaded["type"] == ActionType.UpdateRemote
    assert uploaded["expected_hash"] == "srv"

    restored = resolve_action({**conflict, "decision": "revert"})
    assert restored["type"] == ActionType.UpdateLocal
    assert restored["file_hash"] == "srv"


def test_take_server_never_uploads_or_deletes_remotely():
    actions = [
        {"type": ActionType.Download, "file": "new"},
        {"type": ActionType.UpdateRemote, "file": "edit", "expected_hash": "srv"},
        {"type": ActionType.Upload, "file": "local-only"},
        {"type": ActionType.DeleteRemote, "file": "gone", "file_hash": "srv", "uuid": "u"},
        {"type": ActionType.Conflict, "file": "both", "server_hash": "srv", "uuid": "c", "id": 1},
    ]
    resolved = [resolve_action({**action, "decision": "take_server"}) for action in actions]
    assert resolved[0]["type"] == ActionType.Download
    assert resolved[1]["type"] == ActionType.UpdateLocal
    assert resolved[2]["type"] == ActionType.DeleteLocal
    assert resolved[3]["type"] == ActionType.Download
    assert resolved[4]["type"] == ActionType.UpdateLocal
    assert all(item["type"] not in (ActionType.Upload, ActionType.UpdateRemote, ActionType.DeleteRemote) for item in resolved)


def test_review_rows_round_trip_decisions():
    check_data = {
        "datasheet": {"sync_actions": [
            {"type": ActionType.UpdateRemote, "file": "a.pdf", "path": "Docs"},
            {"type": ActionType.Conflict, "file": "b.pdf", "server_hash": "s"},
        ]},
        "symbols": {"sync_actions": {"lib_dir_sync_actions": {
            "KiPart": [{"type": ActionType.Download, "file": "R"}],
        }}},
    }
    rows = iter_change_rows(check_data)
    assert [row.path for row in rows] == ["Docs/a.pdf", "b.pdf", "KiPart/R"]
    assert rows[1].decision == "ignore"
    rows[0].decision = "revert"
    write_decisions(rows)
    assert check_data["datasheet"]["sync_actions"][0]["decision"] == "revert"

    mark_take_server(check_data)
    assert all(action["decision"] == "take_server" for action in check_data["datasheet"]["sync_actions"])


def test_in_use_error_lists_the_referencing_part():
    text = _format_in_use({
        "error": "Delete rejected: still in use",
        "inUse": [{
            "entity": "symbol",
            "name": "R_Small",
            "usedBy": [{"entity": "part", "name": "Resistor 10k"}],
        }],
    })
    assert "R_Small" in text
    assert "part 'Resistor 10k'" in text
