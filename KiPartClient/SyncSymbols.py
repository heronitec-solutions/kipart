import os
import datetime
import tempfile
import subprocess
import sys
from pathlib import Path
from collections import Counter

from .Misc import ActionType, ReturnCode, RemoteChange, getSymbolValue, getKiCadCliPath
from .ChangeReview import resolve_action
from .RestAPI import RestAPI
from .Canonical import canonicalSymbolText, sha256Text, sha256Bytes
from .MetaFile import load as loadMeta, save as saveMeta, ensureV2, classifyContent, metaEntry
from .sexpdata import loads, dumps, Symbol
from .SymbolLibraryDir import (
    SYMBOL_LIB_EXTENSION, DEFAULT_SYMBOL_LIB_VERSION,
    readSymbolLibrary, findSymbol, saveSymbol, deleteSymbol, writePackedSymbol,
)


MEDIA_SEXPR = 'text/x-kicad-sexpr'
MEDIA_SVG = 'image/svg+xml'


class SyncSymbols:
    def __init__(self, config):
        self._config = config
        self._directory = "Symbols"
        self._api_name = "symbol"
        self._meta_key = "symbols"
        self._api = RestAPI(self._config, self._api_name)

    def _normalizeOutputPath(self):
        if not self._config['output_path'].startswith('/') and not (self._config['output_path'][1] == ":"):
            self._config['output_path'] = os.path.dirname(__file__) + '/' + self._config['output_path']

    def _serverHash(self, entry):
        return entry.get('hash') or entry.get('fileHash')

    def check(self, force_remote=False):
        print('Checking symbols ...')
        self._normalizeOutputPath()
        meta = ensureV2(self._config['output_path'], self._api, self._config)
        meta_data = meta.get(self._meta_key) or {}

        read_path = self._config['output_path'] + '/' + self._directory
        if not os.path.exists(read_path):
            os.makedirs(read_path)

        lib_api = RestAPI(self._config, 'libraryfile')
        lib_dirs = lib_api.getFilteredList('Type', '1')

        sync_data = {
            "cntNew": 0, "cntChanged": 0, "cntDeleted": 0, "cntConflict": 0, "cntUnchanged": 0,
            "sync_actions": {"lib_dirs": lib_dirs, "lib_dir_sync_actions": {}},
        }
        meta_dirty = False

        for lib_dir in lib_dirs:
            lib_filename = lib_dir['filename']
            lib_path = Path(read_path) / (lib_filename + SYMBOL_LIB_EXTENSION)
            db_entries = self._api.getFilteredList('LibraryFileId', str(lib_dir['id']))
            meta_lib = dict(meta_data.get(lib_filename) or {})

            sync_actions = []
            adopted = {}
            num_all = 0

            if lib_filename not in meta_data or (force_remote and not lib_path.is_dir()):
                if lib_filename not in meta_data:
                    print('Symbol library', lib_filename, 'not found in meta file')
                else:
                    print('Symbol library directory', str(lib_path), 'missing, downloading from server')
                for db_entry in db_entries:
                    sync_actions.append({
                        "type": ActionType.Download,
                        "file": db_entry['name'],
                        "uuid": str(db_entry['uuid']),
                        "id": db_entry['id'],
                        "file_hash": self._serverHash(db_entry),
                        "revision_id": db_entry.get('headRevisionId'),
                    })
            elif not lib_path.is_dir():
                print('Symbol library directory', str(lib_path), 'not found, skipping library')
                continue
            else:
                symbol_files = []
                for symbol in readSymbolLibrary(lib_path):
                    text = canonicalSymbolText(symbol['data'])
                    symbol_files.append({
                        'filename': symbol['name'],
                        'file_hash': sha256Text(text),
                        'data': symbol['data'],
                        'canonical': text,
                    })
                num_all = len(symbol_files)
                local_by_name = {s['filename']: s for s in symbol_files}
                matched_local = set()
                matched_meta = set()

                for db_entry in db_entries:
                    uuid = str(db_entry['uuid'])
                    server_hash = self._serverHash(db_entry)
                    server_name = db_entry['name']
                    meta_entry = meta_lib.get(uuid)
                    local = None
                    if meta_entry:
                        local = local_by_name.get(meta_entry.get('name'))
                        if local is None and meta_entry.get('name') != server_name:
                            local = local_by_name.get(server_name)
                    else:
                        local = local_by_name.get(server_name)

                    if meta_entry is None and local is None:
                        sync_actions.append({
                            "type": ActionType.Download,
                            "file": server_name, "uuid": uuid, "id": db_entry['id'],
                            "file_hash": server_hash, "revision_id": db_entry.get('headRevisionId'),
                        })
                    elif meta_entry is not None and local is None:
                        # deleted locally, or rename on server with local still missing old name
                        if meta_entry.get('name') != server_name and meta_entry.get('hash') == server_hash:
                            # remote rename; local file gone under both names → download under new name
                            sync_actions.append({
                                "type": ActionType.Download,
                                "file": server_name, "uuid": uuid, "id": db_entry['id'],
                                "file_hash": server_hash, "revision_id": db_entry.get('headRevisionId'),
                                "old_name": meta_entry.get('name'),
                            })
                        else:
                            sync_actions.append({
                                "type": ActionType.DeleteRemote,
                                "file": meta_entry.get('name') or server_name,
                                "uuid": uuid, "id": db_entry['id'],
                                "file_hash": meta_entry.get('hash') or server_hash,
                                "expected_hash": meta_entry.get('hash') or server_hash,
                            })
                        matched_meta.add(uuid)
                    elif meta_entry is None and local is not None:
                        # Upload succeeded but the create result was not written to meta.
                        # Same content on both sides is already in sync.
                        if local['file_hash'] and local['file_hash'] == server_hash:
                            adopted[uuid] = {
                                'name': server_name,
                                'hash': server_hash,
                                'revision_id': db_entry.get('headRevisionId'),
                            }
                        else:
                            sync_actions.append({
                                "type": ActionType.Conflict,
                                "file": server_name, "uuid": uuid, "id": db_entry['id'],
                                "comment": "Local and remote version of symbol are new",
                                "server_hash": server_hash,
                                "revision_id": db_entry.get('headRevisionId'),
                                "local_hash": local['file_hash'],
                            })
                        matched_local.add(local['filename'])
                    else:
                        matched_meta.add(uuid)
                        matched_local.add(local['filename'])
                        local_hash = local['file_hash']
                        state, dirty = classifyContent(meta_entry, server_hash, local_hash)
                        if dirty:
                            meta_dirty = True

                        # remote rename (same content, different name)
                        if meta_entry.get('name') != server_name and state == 'unchanged':
                            if local['filename'] == meta_entry.get('name'):
                                sync_actions.append({
                                    "type": ActionType.RenameLocal,
                                    "file": meta_entry.get('name'),
                                    "new_name": server_name,
                                    "uuid": uuid, "id": db_entry['id'],
                                    "file_hash": server_hash,
                                    "revision_id": db_entry.get('headRevisionId'),
                                })
                            # else already renamed locally; treat as unchanged meta update later
                            continue

                        if state == 'server':
                            sync_actions.append({
                                "type": ActionType.UpdateLocal,
                                "file": server_name, "uuid": uuid, "id": db_entry['id'],
                                "file_hash": server_hash, "revision_id": db_entry.get('headRevisionId'),
                            })
                        elif state == 'local':
                            sync_actions.append({
                                "type": ActionType.UpdateRemote,
                                "file": local['filename'], "uuid": uuid, "id": db_entry['id'],
                                "file_hash": local_hash, "expected_hash": server_hash,
                                "canonical": local.get('canonical'),
                                "library_file_id": lib_dir['id'],
                            })
                        elif state == 'conflict':
                            sync_actions.append({
                                "type": ActionType.Conflict,
                                "file": local['filename'], "uuid": uuid, "id": db_entry['id'],
                                "comment": "Local and remote version of symbol have changed!",
                                "server_hash": server_hash,
                                "revision_id": db_entry.get('headRevisionId'),
                                "local_hash": local_hash,
                            })

                # remaining local files
                remaining_local = [s for s in symbol_files if s['filename'] not in matched_local]
                remaining_meta = {u: e for u, e in meta_lib.items() if u not in matched_meta}

                # rename detection: Upload + DeleteRemote with same hash
                uploads = []
                for local in remaining_local:
                    # was it in remaining meta by name?
                    meta_uuid = None
                    for u, e in list(remaining_meta.items()):
                        if e.get('name') == local['filename']:
                            meta_uuid = u
                            break
                    if meta_uuid is not None:
                        sync_actions.append({
                            "type": ActionType.DeleteLocal,
                            "file": local['filename'], "uuid": meta_uuid,
                        })
                        remaining_meta.pop(meta_uuid, None)
                    else:
                        uploads.append(local)

                delete_remotes = [a for a in sync_actions if a['type'] == ActionType.DeleteRemote]
                used_deletes = set()
                used_uploads = set()
                for i, local in enumerate(uploads):
                    for j, dr in enumerate(delete_remotes):
                        if j in used_deletes:
                            continue
                        if dr.get('file_hash') == local['file_hash'] or dr.get('expected_hash') == local['file_hash']:
                            # RenameRemote
                            sync_actions.remove(dr)
                            sync_actions.append({
                                "type": ActionType.RenameRemote,
                                "file": local['filename'],
                                "old_name": dr['file'],
                                "uuid": dr['uuid'],
                                "id": dr.get('id'),
                                "file_hash": local['file_hash'],
                                "expected_hash": dr.get('expected_hash') or dr.get('file_hash'),
                                "library_file_id": lib_dir['id'],
                            })
                            used_deletes.add(j)
                            used_uploads.add(i)
                            break

                for i, local in enumerate(uploads):
                    if i in used_uploads:
                        continue
                    sync_actions.append({
                        "type": ActionType.Upload,
                        "file": local['filename'],
                        "file_hash": local['file_hash'],
                        "canonical": local.get('canonical'),
                        "library_file_id": lib_dir['id'],
                    })

                for u, e in remaining_meta.items():
                    sync_actions.append({
                        "type": ActionType.DeleteLocal,
                        "file": e.get('name'), "uuid": u,
                    })

            if adopted:
                meta.setdefault(self._meta_key, {}).setdefault(lib_filename, {}).update(adopted)
                meta_dirty = True

            action_counts = Counter(a['type'] for a in sync_actions)
            print("Symbols in library", lib_filename, "analyzed:")
            print("Download:", action_counts[ActionType.Download])
            print("Upload:", action_counts[ActionType.Upload])
            print("Delete:", action_counts[ActionType.DeleteRemote] + action_counts[ActionType.DeleteLocal])
            print("Update:", action_counts[ActionType.UpdateRemote] + action_counts[ActionType.UpdateLocal])
            print("Rename:", action_counts[ActionType.RenameLocal] + action_counts[ActionType.RenameRemote])
            print("Conflict:", action_counts[ActionType.Conflict])

            sync_data["cntNew"] += action_counts[ActionType.Download] + action_counts[ActionType.Upload]
            sync_data["cntChanged"] += (
                action_counts[ActionType.UpdateRemote] + action_counts[ActionType.UpdateLocal]
                + action_counts[ActionType.RenameLocal] + action_counts[ActionType.RenameRemote]
            )
            sync_data["cntDeleted"] += action_counts[ActionType.DeleteRemote] + action_counts[ActionType.DeleteLocal]
            sync_data["cntConflict"] += action_counts[ActionType.Conflict]
            unchanged = num_all + action_counts[ActionType.Download] - len(sync_actions)
            sync_data["cntUnchanged"] += max(0, unchanged)
            sync_data["sync_actions"]["lib_dir_sync_actions"][lib_filename] = sync_actions

        if meta_dirty:
            saveMeta(self._config['output_path'], meta)

        return sync_data

    def sync(self, sync_actions, sub_progress_callback):
        """Execute local actions; return list of RemoteChange for central commit."""
        print('Syncing symbols ...')
        self._normalizeOutputPath()
        meta = loadMeta(self._config['output_path'])
        remote_changes = []

        prog_cnt = 0
        prog_cnt_total = 0
        for lib_dir in sync_actions["lib_dirs"]:
            if lib_dir['filename'] not in sync_actions["lib_dir_sync_actions"]:
                continue
            prog_cnt_total += len(sync_actions["lib_dir_sync_actions"][lib_dir['filename']])

        if prog_cnt_total > 0:
            sub_progress_callback(True, False, "", prog_cnt_total)

        for lib_dir in sync_actions["lib_dirs"]:
            lib_filename = lib_dir['filename']
            if lib_filename not in sync_actions["lib_dir_sync_actions"]:
                continue
            sync_actions_lib = sync_actions["lib_dir_sync_actions"][lib_filename]
            meta.setdefault(self._meta_key, {}).setdefault(lib_filename, {})

            for sync_action in sync_actions_lib:
                prog_txt = ""
                resolved = resolve_action(sync_action)
                if resolved is None:
                    prog_cnt += 1
                    sub_progress_callback(False, False, sync_action.get('file', '') + " ignored", prog_cnt)
                    continue
                sync_action = resolved
                t = sync_action['type']
                if t == ActionType.Download or t == ActionType.UpdateLocal:
                    self.__downloadSymbol(
                        sync_action['file'], sync_action['id'], lib_filename, lib_dir.get('version'),
                    )
                    meta[self._meta_key][lib_filename][sync_action['uuid']] = metaEntry(
                        sync_action['file'],
                        sync_action['file_hash'],
                        sync_action.get('revision_id'),
                        self._contentHash(sync_action['file'], lib_filename),
                    )
                    # drop old name key if rename-download
                    prog_txt = "downloaded" if t == ActionType.Download else "updated locally"
                elif t == ActionType.DeleteLocal:
                    self.__deleteLocalSymbol(sync_action['file'], lib_filename)
                    if sync_action.get('uuid'):
                        meta[self._meta_key][lib_filename].pop(sync_action['uuid'], None)
                    prog_txt = "deleted"
                elif t == ActionType.RenameLocal:
                    self.__renameLocalSymbol(sync_action['file'], sync_action['new_name'], lib_filename)
                    meta[self._meta_key][lib_filename][sync_action['uuid']] = metaEntry(
                        sync_action['new_name'],
                        sync_action['file_hash'],
                        sync_action.get('revision_id'),
                        self._contentHash(sync_action['new_name'], lib_filename),
                    )
                    prog_txt = "renamed locally"
                elif t in (ActionType.Upload, ActionType.UpdateRemote, ActionType.DeleteRemote, ActionType.RenameRemote):
                    rc = self.__buildRemoteChange(sync_action, lib_dir)
                    if rc is not None:
                        remote_changes.append(rc)
                    prog_txt = "queued for commit"
                elif t == ActionType.Conflict:
                    prog_txt = "conflict (skipped)"

                prog_cnt += 1
                sub_progress_callback(False, False, sync_action.get('file', '') + " " + prog_txt, prog_cnt)

            meta["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f %z')
            saveMeta(self._config['output_path'], meta)

        if prog_cnt_total > 0:
            sub_progress_callback(False, True, "", 0)

        print("Symbols synchronized (local); remote changes:", len(remote_changes))
        return remote_changes

    def __buildRemoteChange(self, sync_action, lib_dir):
        t = sync_action['type']
        lib_filename = lib_dir['filename']
        library_file_id = sync_action.get('library_file_id') or lib_dir['id']

        if t == ActionType.DeleteRemote:
            return RemoteChange({
                "entity": "symbol",
                "op": "delete",
                "uuid": sync_action['uuid'],
                "expectedHash": sync_action.get('expected_hash') or sync_action.get('file_hash'),
            }, summary=f"delete symbol {sync_action.get('file')}", library_filename=lib_filename)

        if t == ActionType.RenameRemote:
            return RemoteChange({
                "entity": "symbol",
                "op": "rename",
                "uuid": sync_action['uuid'],
                "expectedHash": sync_action.get('expected_hash') or sync_action.get('file_hash'),
                "name": sync_action['file'],
                "libraryFileId": library_file_id,
            }, summary=f"rename symbol {sync_action.get('old_name')} -> {sync_action['file']}", library_filename=lib_filename)

        # Upload / UpdateRemote — need content + preview
        symbol_name = sync_action['file']
        built = self.__prepareSymbolPayload(symbol_name, library_file_id, lib_filename)
        if built is None:
            return None
        change, blobs = built
        if t == ActionType.Upload:
            change['op'] = 'create'
        else:
            change['op'] = 'update'
            change['uuid'] = sync_action['uuid']
            change['expectedHash'] = sync_action.get('expected_hash') or sync_action.get('file_hash')
        return RemoteChange(change, blobs, summary=f"{change['op']} symbol {symbol_name}", library_filename=lib_filename)

    def __prepareSymbolPayload(self, symbol_name, library_file_id, library_file):
        lib_path = self.__getLibraryPath(library_file)
        try:
            entry = findSymbol(lib_path, symbol_name)
        except Exception:
            return None
        if entry is None:
            return None
        symbol_data = entry['data']
        canonical = canonicalSymbolText(symbol_data)
        blob_hash = sha256Text(canonical)

        in_bom = getSymbolValue(symbol_data, 'in_bom')
        in_bom = (Symbol("yes") in in_bom[0]) if in_bom else False
        on_board = getSymbolValue(symbol_data, 'on_board')
        on_board = (Symbol("yes") in on_board[0]) if on_board else False
        pin_numbers_hidden = getSymbolValue(symbol_data, 'pin_numbers')
        pin_numbers_hidden = (Symbol("hide") in pin_numbers_hidden[0]) if pin_numbers_hidden else False
        pin_names_hidden = getSymbolValue(symbol_data, 'pin_names')
        pin_names_offset = 0
        pin_names_hide = False
        if pin_names_hidden:
            if len(pin_names_hidden[0]) > 2:
                pin_names_offset = pin_names_hidden[0][1][1]
            pin_names_hide = (Symbol("hide") in pin_names_hidden[0])

        description = ""
        reference = ""
        for elem in getSymbolValue(symbol_data, 'property'):
            if len(elem) > 2 and elem[1] == "ki_description":
                description = elem[2]
            if len(elem) > 2 and elem[1] == "Reference":
                reference = elem[2]

        preview = self.__getPreviewImage(lib_path, symbol_name)
        blobs = [{"hash": blob_hash, "bytes": canonical.encode('utf-8'), "media_type": MEDIA_SEXPR}]
        change = {
            "entity": "symbol",
            "blobHash": blob_hash,
            "libraryFileId": library_file_id,
            "name": symbol_name,
            "reference": reference,
            "inBom": in_bom,
            "onBoard": on_board,
            "pinNumbersHidden": pin_numbers_hidden,
            "pinNamesHidden": pin_names_hide,
            "pinNamesOffset": pin_names_offset,
            "description": description,
        }
        if preview:
            preview_hash = sha256Text(preview)
            blobs.append({"hash": preview_hash, "bytes": preview.encode('utf-8'), "media_type": MEDIA_SVG})
            change["previewBlobHash"] = preview_hash
        return change, blobs

    def __getLibraryPath(self, library_file):
        return Path(self._config['output_path'] + '/' + self._directory) / (library_file + SYMBOL_LIB_EXTENSION)

    def _contentHash(self, symbol_name, library_file):
        try:
            entry = findSymbol(self.__getLibraryPath(library_file), symbol_name)
        except Exception:
            return None
        if entry is None:
            return None
        return sha256Text(canonicalSymbolText(entry['data']))

    def __downloadSymbol(self, symbol_name, symbol_id, library_file, library_version=None):
        print('Downloading symbol: ' + symbol_name)
        try:
            entry_data = self._api.get(symbol_id)
        except Exception:
            return ReturnCode.NoConnection
        data = entry_data.get('data') or ''
        try:
            saveSymbol(
                self.__getLibraryPath(library_file),
                loads(data),
                library_version or DEFAULT_SYMBOL_LIB_VERSION,
            )
        except Exception:
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __deleteLocalSymbol(self, symbol_name, library_file):
        print('Delete local symbol: ' + symbol_name)
        try:
            deleteSymbol(self.__getLibraryPath(library_file), symbol_name)
        except Exception:
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __renameLocalSymbol(self, old_name, new_name, library_file):
        print('Rename local symbol:', old_name, '->', new_name)
        lib_path = self.__getLibraryPath(library_file)
        try:
            entry = findSymbol(lib_path, old_name)
            if entry is None:
                return ReturnCode.FileReadError
            data = entry['data']
            # update symbol name inside sexp (2nd element)
            if isinstance(data, list) and len(data) >= 2:
                data[1] = new_name
            version = entry.get('version') or DEFAULT_SYMBOL_LIB_VERSION
            deleteSymbol(lib_path, old_name)
            saveSymbol(lib_path, data, version)
        except Exception as e:
            print('Rename failed:', e)
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __getPreviewImage(self, library_path, symbol_name):
        file_data = ""
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            preview_library = Path(tmp_dir_name) / "preview.kicad_sym"
            try:
                if not writePackedSymbol(library_path, symbol_name, preview_library):
                    return file_data
            except Exception:
                return file_data

            cmd = [
                getKiCadCliPath(), "sym", "export", "svg",
                "--output", tmp_dir_name, "--symbol", symbol_name, preview_library.as_posix(),
            ]
            CREATE_NO_WINDOW = 0x08000000
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            except OSError as e:
                print("Error running kicad-cli for preview image of symbol '", symbol_name, "':", e, file=sys.stderr)
                return file_data
            if result.returncode == 0:
                output_file = tmp_dir_name + "/" + symbol_name + "_unit1.svg"
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        file_data = f.read()
                except Exception:
                    file_data = ""
            else:
                print("Error exporting preview image for symbol '", symbol_name, "':", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
        return file_data
