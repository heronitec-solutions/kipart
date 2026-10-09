"""Per-file decisions after a library scan, and forced download (local := server)."""

from .Misc import ActionType


DECISION_APPLY = "apply"
DECISION_IGNORE = "ignore"
DECISION_REVERT = "revert"
DECISION_TAKE_SERVER = "take_server"

_CATEGORY = {
    "model3d": "3D model",
    "datasheet": "Datasheet",
    "template": "Template",
    "footprint_libraries": "Footprint library",
    "symbol_libraries": "Symbol library",
    "footprints": "Footprint",
    "symbols": "Symbol",
}

_CHANGE = {
    ActionType.Download: "New on server",
    ActionType.Upload: "New locally",
    ActionType.UpdateLocal: "Changed on server",
    ActionType.UpdateRemote: "Changed locally",
    ActionType.DeleteLocal: "Deleted on server",
    ActionType.DeleteRemote: "Deleted locally",
    ActionType.RenameLocal: "Renamed on server",
    ActionType.RenameRemote: "Renamed locally",
    ActionType.Conflict: "Conflict",
}

DECISION_LABELS = {
    DECISION_APPLY: "Apply",
    DECISION_IGNORE: "Ignore",
    DECISION_REVERT: "Revert",
}


class ChangeRow:
    def __init__(self, category, path, change, action):
        self.category = category
        self.path = path
        self.change = change
        self.action = action
        self.decision = action.get("decision") or default_decision(action)


def default_decision(action):
    if action.get("type") == ActionType.Conflict:
        return DECISION_IGNORE
    return DECISION_APPLY


def iter_change_rows(check_data):
    rows = []
    if not check_data:
        return rows
    for category, library, action in _iter_actions(check_data):
        rows.append(ChangeRow(
            _CATEGORY.get(category, category),
            _action_path(action, library),
            _CHANGE.get(action.get("type"), str(action.get("type"))),
            action,
        ))
    return rows


def write_decisions(rows):
    for row in rows:
        row.action["decision"] = row.decision


def mark_take_server(check_data):
    """Mark every scanned action so the local files match the server. Nothing is uploaded."""
    for _, _, action in _iter_actions(check_data or {}):
        action["decision"] = DECISION_TAKE_SERVER


def resolve_action(action):
    """
    Return the action to execute, or None to skip.

    apply: planned sync direction (a conflict uploads the local file)
    ignore: skip
    revert: undo the change (local edits are discarded; server-only changes are pushed back)
    take_server: make the local file match the server, never upload or delete remotely
    """
    if not action:
        return None
    if _is_library_container(action):
        return _resolve_library(action)

    decision = action.get("decision")
    kind = action.get("type")
    if decision in (None, "", DECISION_APPLY):
        if kind == ActionType.Conflict and decision == DECISION_APPLY:
            return _as_update_remote(action)
        return action
    if decision == DECISION_IGNORE:
        return None
    if decision == DECISION_TAKE_SERVER:
        return _as_take_server(action)
    if decision == DECISION_REVERT:
        return _as_opposite(action)
    return action


def _iter_actions(check_data):
    for key in ("model3d", "datasheet", "template", "footprint_libraries", "symbol_libraries"):
        block = check_data.get(key) or {}
        for action in block.get("sync_actions") or []:
            yield key, None, action
    for key in ("footprints", "symbols"):
        block = check_data.get(key) or {}
        nested = (block.get("sync_actions") or {}).get("lib_dir_sync_actions") or {}
        for library, actions in nested.items():
            for action in actions or []:
                yield key, library, action


def _action_path(action, library):
    name = action.get("file") or action.get("library") or action.get("path_key") or "?"
    folder = (action.get("path") or "").strip("/")
    if folder and action.get("file"):
        name = folder + "/" + action["file"]
    if library:
        name = library + "/" + name
    kind = action.get("type")
    if kind == ActionType.RenameLocal and action.get("new_name"):
        name = name + " → " + action["new_name"]
    elif kind == ActionType.RenameRemote and action.get("old_name"):
        name = action["old_name"] + " → " + name
    return name


def _is_library_container(action):
    return "library" in action and "file" not in action and "uuid" not in action


def _copy(action, **overrides):
    out = dict(action)
    out.update(overrides)
    return out


def _server_hash(action):
    return action.get("server_hash") or action.get("expected_hash") or action.get("file_hash")


def _as_update_local(action):
    return _copy(action, type=ActionType.UpdateLocal, file_hash=_server_hash(action))


def _as_update_remote(action):
    return _copy(
        action,
        type=ActionType.UpdateRemote,
        expected_hash=action.get("server_hash") or action.get("expected_hash"),
        file_hash=action.get("local_hash") or action.get("file_hash"),
    )


def _as_take_server(action):
    kind = action.get("type")
    if kind in (
        ActionType.Download, ActionType.UpdateLocal, ActionType.DeleteLocal, ActionType.RenameLocal,
    ):
        return action
    if kind in (ActionType.UpdateRemote, ActionType.Conflict):
        return _as_update_local(action)
    if kind == ActionType.Upload:
        return _copy(action, type=ActionType.DeleteLocal)
    if kind == ActionType.DeleteRemote:
        return _copy(
            action,
            type=ActionType.Download,
            file_hash=action.get("file_hash") or action.get("expected_hash"),
        )
    if kind == ActionType.RenameRemote:
        return _copy(
            action,
            type=ActionType.RenameLocal,
            new_name=action.get("old_name"),
            file_hash=action.get("expected_hash") or action.get("file_hash"),
        )
    return action


def _as_opposite(action):
    kind = action.get("type")
    if kind == ActionType.Download:
        return _copy(
            action,
            type=ActionType.DeleteRemote,
            expected_hash=action.get("expected_hash") or action.get("file_hash"),
        )
    if kind == ActionType.UpdateLocal:
        return _copy(action, type=ActionType.UpdateRemote, expected_hash=action.get("file_hash"))
    if kind == ActionType.DeleteLocal:
        return _copy(action, type=ActionType.Upload)
    if kind == ActionType.RenameLocal:
        return _copy(
            action,
            type=ActionType.RenameRemote,
            expected_hash=action.get("expected_hash") or action.get("file_hash"),
        )
    if kind in (ActionType.UpdateRemote, ActionType.Conflict):
        return _as_update_local(action)
    if kind == ActionType.Upload:
        return _copy(action, type=ActionType.DeleteLocal)
    if kind == ActionType.DeleteRemote:
        return _copy(
            action,
            type=ActionType.Download,
            file_hash=action.get("file_hash") or action.get("expected_hash"),
        )
    if kind == ActionType.RenameRemote:
        return _copy(
            action,
            type=ActionType.RenameLocal,
            new_name=action.get("old_name"),
            file_hash=action.get("expected_hash") or action.get("file_hash"),
        )
    return action


def _resolve_library(action):
    decision = action.get("decision")
    kind = action.get("type")
    if decision in (None, "", DECISION_APPLY):
        if kind == ActionType.Conflict and decision == DECISION_APPLY:
            return _copy(action, type=ActionType.Download)
        return action
    if decision == DECISION_IGNORE:
        return None
    if decision == DECISION_TAKE_SERVER:
        if kind in (ActionType.Download, ActionType.DeleteLocal):
            return action
        if kind == ActionType.Upload:
            return _copy(action, type=ActionType.DeleteLocal)
        if kind in (ActionType.DeleteRemote, ActionType.Conflict):
            return _copy(action, type=ActionType.Download)
        return action
    if decision == DECISION_REVERT:
        if kind == ActionType.Download:
            return _copy(action, type=ActionType.DeleteRemote)
        if kind == ActionType.Upload:
            return _copy(action, type=ActionType.DeleteLocal)
        if kind == ActionType.DeleteLocal:
            return _copy(action, type=ActionType.Upload)
        if kind == ActionType.DeleteRemote:
            return _copy(action, type=ActionType.Download)
        if kind == ActionType.Conflict:
            return _copy(action, type=ActionType.DeleteLocal)
        return action
    return action
