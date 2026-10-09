import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from KiPartClient.sexpdata import loads, dumps
from KiPartClient.Canonical import (
    canonicalSymbolText, canonicalFootprintText, sha256Text, sha256Bytes,
    extractModels, setModelPaths, stripPathVariable, filePathKey, PLACEHOLDER,
)
from KiPartClient.MetaFile import migrateV1, emptyMeta, save as saveMeta, load as loadMeta
from KiPartClient.Misc import ActionType, RemoteChange
from KiPartClient.RestAPI import RestAPI, CommitConflict, ApiError
from KiPartClient.LibrarySync import _orderChanges, commitRemoteChanges


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_canonical_symbol_idempotent():
    lib = loads(_read("TEST_R.kicad_sym"))
    symbol = next(e for e in lib if isinstance(e, list) and len(e) >= 2 and str(e[0]) == "symbol")
    t1 = canonicalSymbolText(symbol)
    t2 = canonicalSymbolText(loads(t1))
    assert t1 == t2
    assert t1.endswith("\n")
    assert not t1.endswith("\n\n")
    assert sha256Text(t1) == sha256Bytes(t1.encode("utf-8"))


def test_canonical_footprint_idempotent_and_placeholder():
    for name in ("TEST_NO_MODEL.kicad_mod", "TEST_ONE_MODEL.kicad_mod", "TEST_TWO_MODELS.kicad_mod"):
        parsed = loads(_read(name))
        t1 = canonicalFootprintText(parsed)
        t2 = canonicalFootprintText(loads(t1))
        assert t1 == t2, name
        assert "${KIPART" not in t1
        assert "${KICAD" not in t1
        assert "\\\\" not in t1
        if name != "TEST_NO_MODEL.kicad_mod":
            assert PLACEHOLDER in t1


def test_extract_models_and_set_paths_roundtrip():
    parsed = loads(_read("TEST_TWO_MODELS.kicad_mod"))
    models = extractModels(parsed)
    assert len(models) == 2
    assert models[0]["filename"] == "C_0402_1005Metric.step"
    assert models[0]["directory"] == "Capacitors"
    assert models[0]["rotate"] == [0.0, 0.0, 90.0]
    assert models[1]["filename"] == "Alt.wrl"
    assert models[1]["opacity"] == 0.5
    assert models[1]["hide"] is True

    setModelPaths(parsed, {0: "${X}/A/a.step", 1: "${X}/B/b.wrl"})
    models2 = extractModels(parsed)
    assert models2[0]["directory"] == "A"
    assert models2[0]["filename"] == "a.step"
    assert models2[1]["directory"] == "B"


def test_strip_path_variable():
    assert stripPathVariable("${KIPART_3DMODEL_DIR}/Capacitors/x.step") == "Capacitors/x.step"
    assert stripPathVariable("${FOO}\\Capacitors\\x.step") == "Capacitors/x.step"
    assert stripPathVariable("Capacitors/x.step") == "Capacitors/x.step"


def test_meta_v1_migration(tmp_path):
    config = {
        "output_path": str(tmp_path),
        "api_url": "http://localhost:5229/api",
        "api_user_token": "",
        "path_key": "TEST",
    }
    # write a tiny local symbol matching server name so hash compare can run
    (tmp_path / "Symbols" / "KiPart_Symbols.kicad_symdir").mkdir(parents=True)
    # empty lib is fine — migration keeps v1 hash when local missing

    v1 = {
        "last_sync": "2020-01-01",
        "symbols": [{"KiPart_Symbols": [{"C_Small": ["aabb", "2020"]}]}],
        "footprints": [{"KiPart_Footprints": [{"C_0402_1005Metric": ["ccdd", "2020"]}]}],
        "model3d": [{"Capacitors/C_0402_1005Metric.step": ["eeff", "2020"]}],
        "datasheet": [],
        "template": [],
    }
    saveMeta(tmp_path, v1)

    api = MagicMock()
    api.info.return_value = {"apiVersion": 2, "headCommitId": 1}

    lib_api = MagicMock()
    lib_api.getFilteredList.side_effect = lambda by, val: (
        [{"id": 2, "filename": "KiPart_Symbols"}] if str(val) == "1"
        else [{"id": 1, "filename": "KiPart_Footprints"}]
    )

    symbol_api = MagicMock()
    symbol_api.getFilteredList.return_value = [{
        "uuid": "98100457-52ef-4f07-b021-07daf2966c94",
        "name": "C_Small",
        "hash": "serverhash1",
        "headRevisionId": 1,
    }]
    fp_api = MagicMock()
    fp_api.getFilteredList.return_value = [{
        "uuid": "78017048-d952-496e-86f9-6c0b76dc5c2d",
        "name": "C_0402_1005Metric",
        "hash": "serverhash2",
        "headRevisionId": 1,
    }]
    m3_api = MagicMock()
    m3_api.getList.return_value = [{
        "uuid": "47e83d5d-919b-4f54-baa7-9eee29c73284",
        "directory": "Capacitors/",
        "filename": "C_0402_1005Metric.step",
        "hash": "serverhash3",
        "headRevisionId": 1,
    }]

    def ctor(config, name=""):
        m = MagicMock()
        if name == "libraryfile":
            return lib_api
        if name == "symbol":
            return symbol_api
        if name == "footprint":
            return fp_api
        if name == "model3d":
            return m3_api
        if name in ("datasheet", "template"):
            m.getList.return_value = []
            return m
        m.info = api.info
        return m

    api.__class__ = type("R", (), {"__call__": staticmethod(lambda *a, **k: None)})
    # migrate uses api.__class__(config, name) — make RestAPI-like
    class FakeAPI:
        def __init__(self, config, name=""):
            self._inner = ctor(config, name)
        def __getattr__(self, item):
            return getattr(self._inner, item)
        def info(self):
            return {"apiVersion": 2, "headCommitId": 1}

    fake = FakeAPI(config, "")
    meta = migrateV1(v1, fake, config)
    assert meta["meta_version"] == 2
    assert meta["last_commit_id"] == 1
    assert "98100457-52ef-4f07-b021-07daf2966c94" in meta["symbols"]["KiPart_Symbols"]
    # local hash != server → keep v1 hash
    assert meta["symbols"]["KiPart_Symbols"]["98100457-52ef-4f07-b021-07daf2966c94"]["hash"] == "aabb"
    assert "47e83d5d-919b-4f54-baa7-9eee29c73284" in meta["model3d"]


def test_rename_action_types_exist():
    assert ActionType.RenameLocal
    assert ActionType.RenameRemote


def test_create_commit_records_new_symbols_and_footprints(tmp_path, monkeypatch):
    """Commit results have no name. Creates must still land in .kipart_sync."""
    meta = emptyMeta()
    saveMeta(tmp_path, meta)

    symbol_uuid = "11111111-1111-1111-1111-111111111111"
    footprint_uuid = "22222222-2222-2222-2222-222222222222"

    class FakeAPI:
        def __init__(self, config, api_name=""):
            self.api_name = api_name

        def permissions(self):
            return {"canWrite": True, "authenticated": True}

        def blobExists(self, hashes):
            return []

        def commit(self, payload):
            by_entity = {
                "symbol": symbol_uuid,
                "footprint": footprint_uuid,
            }
            return {
                "commitId": 9,
                "results": [
                    {
                        "entity": change["entity"],
                        "uuid": by_entity[change["entity"]],
                        "id": 1,
                        "revisionId": 50,
                        "revisionNo": 1,
                        "hash": change["blobHash"],
                    }
                    for change in payload["changes"]
                ],
            }

        def getList(self):
            return [{"id": 4, "filename": "Capacitors"}]

    monkeypatch.setattr("KiPartClient.LibrarySync.RestAPI", FakeAPI)

    changes = [
        RemoteChange(
            {"entity": "symbol", "op": "create", "name": "R", "libraryFileId": 3, "blobHash": "abc"},
            library_filename="Devices",
        ),
        RemoteChange(
            {"entity": "footprint", "op": "create", "name": "R_0805", "libraryFileId": 4, "blobHash": "def"},
        ),
    ]
    result, err = commitRemoteChanges(
        {"output_path": str(tmp_path), "api_url": "http://localhost/api", "api_user_token": "t"},
        changes,
        "add parts",
    )
    assert err is None
    assert result["commitId"] == 9
    saved = loadMeta(tmp_path)
    assert saved["symbols"]["Devices"][symbol_uuid] == {
        "name": "R",
        "hash": "abc",
        "content_hash": "abc",
        "revision_id": 50,
    }
    assert saved["footprints"]["Capacitors"][footprint_uuid]["name"] == "R_0805"
    assert saved["footprints"]["Capacitors"][footprint_uuid]["hash"] == "def"
    assert saved["footprints"]["Capacitors"][footprint_uuid]["content_hash"] == "def"
    assert saved["last_commit_id"] == 9


def test_commit_payload_order_and_expected_hash():
    changes = [
        RemoteChange({"entity": "footprint", "op": "update", "expectedHash": "eh", "name": "F"}),
        RemoteChange({"entity": "model3d", "op": "create", "filename": "a.step"}),
        RemoteChange({"entity": "symbol", "op": "update", "expectedHash": "es", "name": "S"}),
        RemoteChange({"entity": "datasheet", "op": "delete", "expectedHash": "ed"}),
    ]
    ordered = _orderChanges(changes)
    entities = [rc.change["entity"] for rc in ordered]
    assert entities == ["model3d", "datasheet", "symbol", "footprint"]
    assert ordered[2].change["expectedHash"] == "es"
    assert ordered[0].change.get("expectedHash") is None  # create


def test_require_write_blocks_read_only_account():
    api = RestAPI({"api_url": "http://localhost/api", "api_user_token": "kpt_reader"}, "")
    api._access = {"authenticated": True, "canWrite": False, "username": "Reader"}
    with pytest.raises(ApiError) as ei:
        api._require_write()
    assert ei.value.status_code == 403
    assert "read-only" in str(ei.value)


def test_commit_conflict_raises():
    class FakeResp:
        status_code = 409
        def json(self):
            return {"conflicts": [{"entity": "symbol", "uuid": "u1", "expectedHash": "a", "actualHash": "b"}]}
        text = "conflict"
        reason = "Conflict"
        request = MagicMock(method="POST", url="http://x/commit")

    api = RestAPI({"api_url": "http://localhost/api", "api_user_token": ""}, "")
    import requests as req_mod
    original = req_mod.post

    def fake_post(*a, **k):
        return FakeResp()

    req_mod.post = fake_post
    try:
        with pytest.raises(CommitConflict) as ei:
            api.commit({"message": "m", "author": "a", "changes": []})
        assert ei.value.conflicts[0]["uuid"] == "u1"
    finally:
        req_mod.post = original


def test_file_path_key():
    assert filePathKey("Capacitors/", "x.step") == "Capacitors/x.step"
    assert filePathKey("", "x.step") == "x.step"


def test_classify_content_ignores_canonical_drift():
    from KiPartClient.MetaFile import classifyContent

    entry = {"hash": "server-raw", "content_hash": "local-canonical"}
    state, dirty = classifyContent(entry, "server-raw", "local-canonical")
    assert state == "unchanged"
    assert dirty is False

    state, dirty = classifyContent(entry, "server-raw", "edited")
    assert state == "local"
    assert dirty is False

    state, dirty = classifyContent(entry, "server-new", "local-canonical")
    assert state == "server"

    state, dirty = classifyContent(entry, "server-new", "edited")
    assert state == "conflict"


def test_reconcile_canonical_after_migration(tmp_path):
    """Server stores raw text; matching canonical local text is recorded as in sync, not as an upload."""
    from KiPartClient.MetaFile import reconcileCanonicalAfterMigration, emptyMeta, save as saveMeta

    # Raw footprint text (no pretty-print / placeholder) vs local already-canonical file
    raw_fp = _read("TEST_ONE_MODEL.kicad_mod").replace("\r\n", "\n")
    # Ensure we have a form that dumps differently: use compact-ish raw if fixture is already pretty
    parsed = loads(raw_fp)
    local_canonical = canonicalFootprintText(parsed)
    # Simulate server storing a different serialisation of the same sexpr (e.g. non-placeholder path)
    # by using dumps without re-normalising models — if identical, mutate whitespace
    server_raw = dumps(parsed, pretty_print=False)
    if not server_raw.endswith("\n"):
        server_raw += "\n"
    server_canonical = canonicalFootprintText(loads(server_raw))
    assert server_canonical == local_canonical
    server_hash = sha256Text(server_raw)
    local_hash = sha256Text(local_canonical)
    # Typically they differ after migration; if fixture already matches, force a distinct server blob
    if server_hash == local_hash:
        server_raw = server_raw.rstrip("\n") + " \n"  # trailing space before newline — may still parse
        # Better: wrap with different formatting via sexpdata roundtrip that still parses equal
        server_raw = dumps(loads(local_canonical), pretty_print=False)
        if not server_raw.endswith("\n"):
            server_raw += "\n"
        server_hash = sha256Text(server_raw)
        server_canonical = canonicalFootprintText(loads(server_raw))
        assert server_canonical == local_canonical
        if server_hash == local_hash:
            pytest.skip("cannot construct distinct raw vs canonical hash for fixture")

    lib_dir = tmp_path / "Footprints" / "KiPart_Footprints.pretty"
    lib_dir.mkdir(parents=True)
    (lib_dir / "C_0402_1005Metric.kicad_mod").write_text(local_canonical, encoding="utf-8")

    uuid = "78017048-d952-496e-86f9-6c0b76dc5c2d"
    meta = emptyMeta(last_commit_id=1)
    meta["footprints"] = {
        "KiPart_Footprints": {
            uuid: {"name": "C_0402_1005Metric", "hash": "old_v1_hash", "revision_id": 1}
        }
    }
    saveMeta(tmp_path, meta)

    config = {
        "output_path": str(tmp_path),
        "api_url": "http://localhost/api",
        "api_user_token": "",
        "path_key": "TEST",
    }

    fp_entry = {
        "id": 1,
        "uuid": uuid,
        "name": "C_0402_1005Metric",
        "hash": server_hash,
        "libraryFileId": 1,
        "headRevisionId": 1,
        "data": server_raw,
    }

    class FakeAPI:
        def __init__(self, config, name=""):
            self._name = name

        def getList(self):
            if self._name == "footprint":
                return [fp_entry]
            if self._name == "symbol":
                return []
            return []

        def get(self, id):
            assert self._name == "footprint"
            return fp_entry

        def info(self):
            return {"apiVersion": 2, "headCommitId": 1}

    pending = reconcileCanonicalAfterMigration(meta, FakeAPI(config, ""), config)
    assert pending == []
    recorded = meta["footprints"]["KiPart_Footprints"][uuid]
    assert recorded["hash"] == server_hash
    assert recorded["content_hash"] == local_hash
    assert "_pending_canonicalize" not in meta

    # Idempotent: second call does not fetch again or queue an upload
    pending2 = reconcileCanonicalAfterMigration(meta, FakeAPI(config, ""), config)
    assert pending2 == []
