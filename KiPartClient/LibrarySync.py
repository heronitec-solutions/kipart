import json
import os
from pathlib import Path

from .SyncFileDirectory import SyncFileDirectory
from .SyncFootprintLibraries import SyncFootprintLibraries
from .SyncFootprints import SyncFootprints
from .SyncSymbolLibraries import SyncSymbolLibraries
from .SyncSymbols import SyncSymbols
from .RestAPI import RestAPI, CommitConflict, ApiError
from .MetaFile import (
    load as loadMeta,
    save as saveMeta,
    ensureV2,
    reconcileCanonicalAfterMigration,
    clearPendingCanonicalize,
    CANONICALIZE_COMMIT_MESSAGE,
)
from .KiCadSettings import registerLibraryTables, ensureKiCadEnvVars
from .Misc import ActionType


_ENTITY_ORDER = {
    'model3d': 0,
    'datasheet': 1,
    'template': 2,
    'symbol': 3,
    'footprint': 4,
}


def _clientVersion():
    try:
        meta_path = Path(__file__).resolve().parent.parent / 'metadata.json'
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data['versions'][0]['version']
    except Exception:
        return '0.0.0'


def _orderChanges(remote_changes):
    return sorted(
        remote_changes,
        key=lambda rc: _ENTITY_ORDER.get((rc.change or {}).get('entity'), 99),
    )


def _pairResult(index, item, ordered, used):
    """Match a commit result to the local change that produced it.

    Results come back in the same order as the submitted changes and do not
    include the symbol or footprint name. Index pairing is what records a
    create in the meta file. UUID and name matching cover older responses.
    """
    entity = item.get('entity')
    uuid = str(item.get('uuid') or '')

    if index < len(ordered) and id(ordered[index]) not in used:
        candidate = ordered[index]
        if (candidate.change or {}).get('entity') == entity:
            return candidate

    for rc in ordered:
        if id(rc) in used:
            continue
        change = rc.change or {}
        if change.get('entity') == entity and change.get('uuid') and str(change['uuid']) == uuid:
            return rc

    result_name = item.get('name')
    for rc in ordered:
        if id(rc) in used:
            continue
        change = rc.change or {}
        if change.get('entity') != entity or change.get('op') != 'create' or change.get('uuid'):
            continue
        if result_name and change.get('name') != result_name and change.get('filename') != result_name:
            continue
        return rc
    return None


def commitRemoteChanges(config, remote_changes, message, sub_progress_callback=None, progress_log=None):
    """
    Upload missing blobs then POST /api/commit.
    Returns (commit_response_or_None, error_message_or_None).
    On 409: marks conflicts, does not update meta for those entries.
    """
    if not remote_changes:
        return None, None

    api = RestAPI(config, "")
    try:
        access = api.permissions()
    except ApiError as exc:
        return None, str(exc)
    if not access.get('canWrite') and not access.get('legacy'):
        if access.get('error') == 'invalid token':
            return None, "The API token was rejected. Create a token in your KiPart account and paste it into the library settings."
        if not access.get('authenticated'):
            return None, "Uploads require an API token with write permission. Create one under My Account and paste it into the library settings."
        if access.get('authType') == 'api-token':
            return None, "This API token is read-only. Create a token with write permission under My Account. Uploads were not sent."
        return None, f"The account '{access.get('username') or ''}' has read-only access. Uploads were not sent."

    ordered = _orderChanges(remote_changes)

    # Collect blobs (dedupe by hash)
    blobs_by_hash = {}
    for rc in ordered:
        for blob in rc.blobs or []:
            blobs_by_hash[blob['hash']] = blob

    hashes = list(blobs_by_hash.keys())
    missing = api.blobExists(hashes) if hashes else []
    to_upload = [blobs_by_hash[h] for h in missing if h in blobs_by_hash]

    if sub_progress_callback and to_upload:
        sub_progress_callback(True, False, "", len(to_upload))
    for i, blob in enumerate(to_upload):
        api.putBlob(blob['hash'], blob['bytes'], blob['media_type'])
        if sub_progress_callback:
            sub_progress_callback(False, False, f"blob {blob['hash'][:12]}… uploaded", i + 1)
    if sub_progress_callback and to_upload:
        sub_progress_callback(False, True, "", 0)

    meta = loadMeta(config['output_path'])
    payload = {
        "message": message,
        "client": f"kipart-client/{_clientVersion()}",
        "baseCommitId": meta.get('last_commit_id'),
        "changes": [rc.change for rc in ordered],
    }

    try:
        result = api.commit(payload)
    except CommitConflict as e:
        msg_lines = ["Commit rejected (409 Conflict):"]
        for c in e.conflicts:
            line = (
                f"  {c.get('entity')} {c.get('uuid')}: expected={c.get('expectedHash')} "
                f"actual={c.get('actualHash')} reason={c.get('reason')}"
            )
            msg_lines.append(line)
            if progress_log:
                progress_log(line)
            # mark matching sync entries as Conflict is caller's concern; we just report
        return None, "\n".join(msg_lines)
    except ApiError as e:
        return None, str(e)

    # Update meta from results. The server returns one result per change, in the
    # same entity order, and create results have a new uuid but no name. Pair by
    # index first so new symbols and footprints are recorded in the meta file.
    results = result.get('results') or []
    used = set()
    for index, item in enumerate(results):
        entity = item.get('entity')
        uuid = str(item.get('uuid'))
        rc = _pairResult(index, item, ordered, used)
        if rc is not None:
            used.add(id(rc))
        change = rc.change if rc else None

        if entity in ('symbol', 'footprint'):
            # need library filename from change
            lib_filename = getattr(rc, 'library_filename', None) if rc else None
            name = None
            if change:
                name = change.get('name')
                # look up library file id
                lib_id = change.get('libraryFileId')
                if lib_filename is None and lib_id is not None:
                    try:
                        libs = RestAPI(config, 'libraryfile').getList()
                        for lib in libs:
                            if lib.get('id') == lib_id:
                                lib_filename = lib.get('filename')
                                break
                    except Exception:
                        pass
            # fallback: search existing meta
            key = 'symbols' if entity == 'symbol' else 'footprints'
            if lib_filename is None:
                for lf, entries in (meta.get(key) or {}).items():
                    if uuid in entries:
                        lib_filename = lf
                        name = name or entries[uuid].get('name')
                        break
            if lib_filename is None:
                # try from any create change
                if change and change.get('libraryFileId'):
                    lib_filename = str(change['libraryFileId'])
            if lib_filename:
                meta.setdefault(key, {}).setdefault(lib_filename, {})
                if change and change.get('op') == 'delete':
                    meta[key][lib_filename].pop(uuid, None)
                else:
                    previous = (meta.get(key) or {}).get(lib_filename, {}).get(uuid) or {}
                    new_hash = item.get('hash')
                    if change and change.get('op') == 'rename':
                        content_hash = previous.get('content_hash') or new_hash
                    else:
                        content_hash = new_hash
                    record = {
                        'name': name or (change or {}).get('name') or '',
                        'hash': new_hash,
                        'revision_id': item.get('revisionId'),
                    }
                    if content_hash:
                        record['content_hash'] = content_hash
                    meta[key][lib_filename][uuid] = record
                    if change and change.get('op') == 'create':
                        change['uuid'] = uuid  # so further matching works
        elif entity in ('model3d', 'datasheet', 'template'):
            if change and change.get('op') == 'delete':
                meta.setdefault(entity, {}).pop(uuid, None)
            else:
                path = None
                if change:
                    from .Canonical import filePathKey
                    path = filePathKey(change.get('directory'), change.get('filename'))
                existing = (meta.get(entity) or {}).get(uuid)
                meta.setdefault(entity, {})[uuid] = {
                    'path': path or (existing or {}).get('path') or '',
                    'hash': item.get('hash'),
                    'revision_id': item.get('revisionId'),
                }

    meta['last_commit_id'] = result.get('commitId')
    saveMeta(config['output_path'], meta)
    return result, None


def checkLibrary(config, progress_callback, finished_callback, force_remote=False):

    api = RestAPI(config, "")

    check_data = {
        "cntNew": 0,
        "cntChanged": 0,
        "cntDeleted": 0,
        "cntConflict": 0,
        "cntUnchanged": 0,
    }

    try:
        changed_vars = ensureKiCadEnvVars(config['path_key'], config['output_path'])
        if changed_vars:
            progress_callback(check_data, "Updated KiCad path variables: " + ", ".join(changed_vars), 0)
    except Exception as e:
        print("Failed to check KiCad path variables:", e)

    try:
        registerLibraryTables(config['name'], config['path_key'], config['output_path'])
    except Exception as e:
        print("Failed to register library tables:", e)

    if not api.checkConnectionStatus():
        info = api.lastInfo
        if info is not None and int(info.get('apiVersion') or 0) < 2:
            finished_callback(check_data, "Server API version < 2 (required for this client)")
        else:
            finished_callback(check_data, "No connection to API!")
        return

    # migrate meta if needed, then reconcile canonical vs migrated server blobs
    try:
        meta = ensureV2(config['output_path'], api, config)
        pending = reconcileCanonicalAfterMigration(meta, api, config)
        if pending:
            progress_callback(
                check_data,
                f"Queued {len(pending)} item(s) for post-migration canonicalisation commit",
                0,
            )
        last_commit = meta.get('last_commit_id') or 0
        changes = api.getChangesSince(last_commit)
        head = changes.get('headCommitId')
        n = abs(int(head or 0) - int(last_commit or 0))
        # Prefer count of commits: head - last_commit
        if head is not None and last_commit is not None and int(head) > int(last_commit):
            n_commits = int(head) - int(last_commit)
            progress_callback(check_data, f"{n_commits} commits since last sync", 0)
        else:
            progress_callback(check_data, "0 commits since last sync", 0)
    except Exception as e:
        print("Failed to query changes since last sync:", e)

    # check 3D models
    progress_callback(check_data, "Checking 3D models", 0)
    try:
        syncEntity = SyncFileDirectory(config, "Packages3D", "model3d")
        check_data["model3d"] = syncEntity.check()

        if check_data["model3d"] is not None:
            check_data["cntNew"] += check_data["model3d"]["cntNew"]
            check_data["cntChanged"] += check_data["model3d"]["cntChanged"]
            check_data["cntDeleted"] += check_data["model3d"]["cntDeleted"]
            check_data["cntConflict"] += check_data["model3d"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["model3d"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check 3D models", 0)
        print("Failed to check 3D models")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    progress_callback(check_data, "Checking Datasheets", 1)
    try:
        syncEntity = SyncFileDirectory(config, "Datasheets", "datasheet")
        check_data["datasheet"] = syncEntity.check()

        if check_data["datasheet"] is not None:
            check_data["cntNew"] += check_data["datasheet"]["cntNew"]
            check_data["cntChanged"] += check_data["datasheet"]["cntChanged"]
            check_data["cntDeleted"] += check_data["datasheet"]["cntDeleted"]
            check_data["cntConflict"] += check_data["datasheet"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["datasheet"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check Datasheets", 1)
        print("Failed to check Datasheets")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    progress_callback(check_data, "Checking Templates", 2)
    try:
        syncEntity = SyncFileDirectory(config, "Templates", "template")
        check_data["template"] = syncEntity.check()

        if check_data["template"] is not None:
            check_data["cntNew"] += check_data["template"]["cntNew"]
            check_data["cntChanged"] += check_data["template"]["cntChanged"]
            check_data["cntDeleted"] += check_data["template"]["cntDeleted"]
            check_data["cntConflict"] += check_data["template"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["template"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check template", 2)
        print("Failed to check template")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    progress_callback(check_data, "Checking footprint libraries", 3)
    try:
        syncEntity = SyncFootprintLibraries(config)
        check_data["footprint_libraries"] = syncEntity.check(force_remote=force_remote)

        if check_data["footprint_libraries"] is not None:
            check_data["cntNew"] += check_data["footprint_libraries"]["cntNew"]
            check_data["cntChanged"] += check_data["footprint_libraries"]["cntChanged"]
            check_data["cntDeleted"] += check_data["footprint_libraries"]["cntDeleted"]
            check_data["cntConflict"] += check_data["footprint_libraries"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["footprint_libraries"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check footprint libraries", 3)
        print("Failed to check footprint libraries")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    progress_callback(check_data, "Checking footprints", 4)
    try:
        syncEntity = SyncFootprints(config)
        check_data["footprints"] = syncEntity.check(force_remote=force_remote)

        if check_data["footprints"] is not None:
            check_data["cntNew"] += check_data["footprints"]["cntNew"]
            check_data["cntChanged"] += check_data["footprints"]["cntChanged"]
            check_data["cntDeleted"] += check_data["footprints"]["cntDeleted"]
            check_data["cntConflict"] += check_data["footprints"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["footprints"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check footprints", 4)
        print("Failed to check footprints")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    progress_callback(check_data, "Checking symbol libraries", 5)
    try:
        syncEntity = SyncSymbolLibraries(config)
        check_data["symbol_libraries"] = syncEntity.check(force_remote=force_remote)

        if check_data["symbol_libraries"] is not None:
            check_data["cntNew"] += check_data["symbol_libraries"]["cntNew"]
            check_data["cntChanged"] += check_data["symbol_libraries"]["cntChanged"]
            check_data["cntDeleted"] += check_data["symbol_libraries"]["cntDeleted"]
            check_data["cntConflict"] += check_data["symbol_libraries"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["symbol_libraries"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check symbol libraries", 5)
        print("Failed to check symbol libraries")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    progress_callback(check_data, "Checking symbols", 6)
    try:
        syncEntity = SyncSymbols(config)
        check_data["symbols"] = syncEntity.check(force_remote=force_remote)

        if check_data["symbols"] is not None:
            check_data["cntNew"] += check_data["symbols"]["cntNew"]
            check_data["cntChanged"] += check_data["symbols"]["cntChanged"]
            check_data["cntDeleted"] += check_data["symbols"]["cntDeleted"]
            check_data["cntConflict"] += check_data["symbols"]["cntConflict"]
            check_data["cntUnchanged"] += check_data["symbols"]["cntUnchanged"]
    except Exception:
        progress_callback(check_data, "Failed to check symbols", 6)
        print("Failed to check symbols")

    if not api.checkConnectionStatus():
        finished_callback(check_data, "Connection to API lost!")
        return

    if check_data["cntNew"] + check_data["cntChanged"] + check_data["cntDeleted"] + check_data["cntConflict"] == 0:
        finished_callback(check_data, "No changes detected")
    elif check_data["cntConflict"] > 0:
        finished_callback(check_data, "There are conflicts")
    else:
        finished_callback(check_data, "")


def syncLibrary(config, sync_data, progress_callback, finished_callback, sub_progress_callback,
                commit_message_provider=None):

    api = RestAPI(config, "")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "No connection to API!")
        return

    try:
        access = api.permissions()
    except ApiError as exc:
        finished_callback(sync_data, str(exc))
        return
    if not access.get('canRead') and not access.get('legacy'):
        if access.get('error') == 'invalid token':
            finished_callback(sync_data, "The API token was rejected. Create a token in your KiPart account and paste it into the library settings.")
        else:
            finished_callback(sync_data, "This server requires an API token to download the library. Create one under My Account and paste it into the library settings.")
        return

    if not access.get('canWrite') and not access.get('legacy'):
        if access.get('authType') == 'api-token':
            progress_callback(sync_data, "This API token is read-only. Downloads continue; uploads are blocked.", 0)
        else:
            progress_callback(sync_data, "Read-only access. Downloads continue; uploads are blocked.", 0)

    all_remote = []

    progress_callback(sync_data, "Syncing 3D models", 0)
    try:
        syncEntity = SyncFileDirectory(config, "Packages3D", "model3d")
        all_remote += syncEntity.sync(sync_data["model3d"]["sync_actions"], sub_progress_callback) or []
    except Exception:
        progress_callback(sync_data, "Failed to sync 3D models", 0)
        print("Failed to sync 3D models")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    progress_callback(sync_data, "Syncing datasheets", 1)
    try:
        syncEntity = SyncFileDirectory(config, "Datasheets", "datasheet")
        all_remote += syncEntity.sync(sync_data["datasheet"]["sync_actions"], sub_progress_callback) or []
    except Exception:
        progress_callback(sync_data, "Failed to sync datasheets", 1)
        print("Failed to sync datasheets")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    progress_callback(sync_data, "Syncing templates", 2)
    try:
        syncEntity = SyncFileDirectory(config, "Templates", "template")
        all_remote += syncEntity.sync(sync_data["template"]["sync_actions"], sub_progress_callback) or []
    except Exception:
        progress_callback(sync_data, "Failed to sync templates", 2)
        print("Failed to sync templates")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    progress_callback(sync_data, "Syncing footprint libraries", 3)
    try:
        syncEntity = SyncFootprintLibraries(config)
        syncEntity.sync(sync_data["footprint_libraries"]["sync_actions"], sub_progress_callback)
    except Exception:
        progress_callback(sync_data, "Failed to sync footprint libraries", 3)
        print("Failed to sync footprint libraries")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    progress_callback(sync_data, "Syncing footprints", 4)
    try:
        syncEntity = SyncFootprints(config)
        all_remote += syncEntity.sync(sync_data["footprints"]["sync_actions"], sub_progress_callback) or []
    except Exception:
        progress_callback(sync_data, "Failed to sync footprints", 4)
        print("Failed to sync footprints")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    progress_callback(sync_data, "Syncing symbol libraries", 5)
    try:
        syncEntity = SyncSymbolLibraries(config)
        syncEntity.sync(sync_data["symbol_libraries"]["sync_actions"], sub_progress_callback)
    except Exception:
        progress_callback(sync_data, "Failed to sync symbol libraries", 5)
        print("Failed to sync symbol libraries")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    progress_callback(sync_data, "Syncing symbols", 6)
    try:
        syncEntity = SyncSymbols(config)
        all_remote += syncEntity.sync(sync_data["symbols"]["sync_actions"], sub_progress_callback) or []
    except Exception:
        progress_callback(sync_data, "Failed to sync symbols", 6)
        print("Failed to sync symbols")

    if not api.checkConnectionStatus():
        finished_callback(sync_data, "Connection to API lost!")
        return

    # Central commit for remote changes
    if all_remote:
        meta = loadMeta(config['output_path'])
        pending = meta.get('_pending_canonicalize') or []
        pending_uuids = {str(p.get('uuid')) for p in pending}

        def _uuid_of(rc):
            return str((rc.change or {}).get('uuid') or '')

        canon_remote = [rc for rc in all_remote if _uuid_of(rc) in pending_uuids and (rc.change or {}).get('op') == 'update']
        user_remote = [rc for rc in all_remote if rc not in canon_remote]

        def _log(line):
            progress_callback(sync_data, line, 6)

        finish_msgs = []

        if canon_remote:
            commit_result, err = commitRemoteChanges(
                config, canon_remote, CANONICALIZE_COMMIT_MESSAGE,
                sub_progress_callback=sub_progress_callback,
                progress_log=_log,
            )
            if err:
                sync_data["cntConflict"] = sync_data.get("cntConflict", 0) + 1
                finished_callback(sync_data, err)
                return
            if commit_result:
                cid = commit_result.get('commitId')
                clearPendingCanonicalize(
                    loadMeta(config['output_path']),
                    config['output_path'],
                    committed_uuids=[_uuid_of(rc) for rc in canon_remote],
                )
                finish_msgs.append(f"Commit #{cid} created: {CANONICALIZE_COMMIT_MESSAGE}")
                _log(finish_msgs[-1])

        if user_remote:
            summary = [rc.summary for rc in user_remote]
            if commit_message_provider is None:
                message = "Sync from KiPart client"
            else:
                result = commit_message_provider(summary)
                if result is None:
                    progress_callback(sync_data, "Upload skipped", 6)
                    msg = "Syncing finished (upload skipped)"
                    if finish_msgs:
                        msg = "\n".join(finish_msgs) + "\n" + msg
                    finished_callback(sync_data, msg)
                    return
                message = result

            commit_result, err = commitRemoteChanges(
                config, user_remote, message,
                sub_progress_callback=sub_progress_callback,
                progress_log=_log,
            )
            if err:
                sync_data["cntConflict"] = sync_data.get("cntConflict", 0) + 1
                finished_callback(sync_data, err)
                return
            if commit_result:
                cid = commit_result.get('commitId')
                finish_msgs.append(f"Commit #{cid} created: {message}")

        if finish_msgs:
            finished_callback(sync_data, "Syncing finished\n" + "\n".join(finish_msgs))
            return

    finished_callback(sync_data, "Syncing finished")
