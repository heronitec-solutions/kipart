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
from .Canonical import (
    canonicalFootprintText, sha256Text, extractModels, setModelPaths, filePathKey,
)
from .MetaFile import load as loadMeta, save as saveMeta, ensureV2, classifyContent, metaEntry
from .sexpdata import loads, dumps, Symbol


MEDIA_SEXPR = 'text/x-kicad-sexpr'
MEDIA_SVG = 'image/svg+xml'


class SyncFootprints:
    def __init__(self, config):
        self._config = config
        self._directory = "Footprints"
        self._api_name = "footprint"
        self._meta_key = "footprints"
        self._api = RestAPI(self._config, self._api_name)

    def _normalizeOutputPath(self):
        if not self._config['output_path'].startswith('/') and not (self._config['output_path'][1] == ":"):
            self._config['output_path'] = os.path.dirname(__file__) + '/' + self._config['output_path']

    def _serverHash(self, entry):
        return entry.get('hash') or entry.get('fileHash')

    def _modelPathPrefix(self):
        return "${" + self._config['path_key'] + "_3DMODEL_DIR}"

    def _resolveModel3dUuid(self, meta, directory, filename):
        path_key = filePathKey(directory, filename)
        for uuid, entry in (meta.get('model3d') or {}).items():
            if filePathKey(*(self._splitPath(entry.get('path', '')))) == path_key or entry.get('path') == path_key:
                return uuid
            # loose match
            if entry.get('path', '').replace('\\', '/').strip('/') == path_key:
                return uuid

        # API fallback: path filter (server may store directory with trailing slash)
        model_api = RestAPI(self._config, 'model3d')
        candidates = [
            path_key,
            f"{(directory or '').rstrip('/')}/{(filename or '')}",
            f"{(directory or '').rstrip('/')}/{(filename or '')}" if directory else filename,
        ]
        if directory:
            # quirk: Directory stored as 'Capacitors/' → filter needs Capactors//file
            candidates.append(f"{directory.rstrip('/')}/ /{filename}".replace(' /', '/'))
            candidates.append(f"{directory.rstrip('/')}//{filename}")
            if not str(directory).endswith('/'):
                candidates.append(f"{directory}/{filename}")
            else:
                candidates.append(f"{directory}{filename}")
                candidates.append(f"{directory.rstrip('/')}//{filename}")

        seen = set()
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            try:
                results = model_api.getFiltered('path', cand)
                if results:
                    return str(results[0]['uuid'])
            except Exception:
                pass

        # searchbyfilename with trailing-slash directory
        try:
            dir_slash = (directory or '')
            if dir_slash and not dir_slash.endswith('/'):
                dir_slash = dir_slash + '/'
            found = model_api.searchForFilenameAndPath(filename, dir_slash)
            if found:
                return str(found[0]['uuid'])
            if directory:
                found = model_api.searchForFilenameAndPath(filename, directory.rstrip('/') + '/')
                if found:
                    return str(found[0]['uuid'])
        except Exception:
            pass
        return None

    @staticmethod
    def _splitPath(path):
        path = (path or '').replace('\\', '/').strip('/')
        if '/' in path:
            d, f = path.rsplit('/', 1)
            return d, f
        return '', path

    def check(self, force_remote=False):
        print('Checking footprints ...')
        self._normalizeOutputPath()
        meta = ensureV2(self._config['output_path'], self._api, self._config)
        meta_data = meta.get(self._meta_key) or {}

        read_path = self._config['output_path'] + '/' + self._directory
        if not os.path.exists(read_path):
            os.makedirs(read_path)

        lib_api = RestAPI(self._config, 'libraryfile')
        lib_dirs = lib_api.getFilteredList('Type', '0')

        sync_data = {
            "cntNew": 0, "cntChanged": 0, "cntDeleted": 0, "cntConflict": 0, "cntUnchanged": 0,
            "sync_actions": {"lib_dirs": lib_dirs, "lib_dir_sync_actions": {}},
        }
        meta_dirty = False

        for lib_dir in lib_dirs:
            lib_filename = lib_dir['filename']
            lib_path = read_path + '/' + lib_filename + '.pretty'
            db_entries = self._api.getFilteredList('LibraryFileId', str(lib_dir['id']))
            meta_lib = dict(meta_data.get(lib_filename) or {})
            sync_actions = []
            adopted = {}
            num_all = 0

            if lib_filename not in meta_data or (force_remote and not os.path.isdir(lib_path)):
                if lib_filename not in meta_data:
                    print('Footprint library', lib_filename, 'not found in meta file')
                else:
                    print('Footprint library directory', lib_path, 'missing, downloading from server')
                for db_entry in db_entries:
                    sync_actions.append({
                        "type": ActionType.Download,
                        "file": db_entry['name'],
                        "uuid": str(db_entry['uuid']),
                        "id": db_entry['id'],
                        "file_hash": self._serverHash(db_entry),
                        "revision_id": db_entry.get('headRevisionId'),
                    })
            else:
                footprint_files = []
                if os.path.isdir(lib_path):
                    for read_file in os.scandir(lib_path):
                        if read_file.is_dir() or not read_file.name.endswith('.kicad_mod'):
                            continue
                        with open(read_file, 'r', encoding='utf-8') as f:
                            parsed = loads(f.read())
                        text = canonicalFootprintText(parsed)
                        footprint_files.append({
                            'filename': read_file.name.replace('.kicad_mod', ''),
                            'file_hash': sha256Text(text),
                            'parsed': parsed,
                            'canonical': text,
                        })
                num_all = len(footprint_files)
                local_by_name = {s['filename']: s for s in footprint_files}
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
                        if meta_entry.get('name') != server_name and meta_entry.get('hash') == server_hash:
                            sync_actions.append({
                                "type": ActionType.Download,
                                "file": server_name, "uuid": uuid, "id": db_entry['id'],
                                "file_hash": server_hash, "revision_id": db_entry.get('headRevisionId'),
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
                                "comment": "Local and remote version of footprint are new",
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
                                "parsed": local.get('parsed'),
                                "library_file_id": lib_dir['id'],
                            })
                        elif state == 'conflict':
                            sync_actions.append({
                                "type": ActionType.Conflict,
                                "file": local['filename'], "uuid": uuid, "id": db_entry['id'],
                                "comment": "Local and remote version of footprint have changed!",
                                "server_hash": server_hash,
                                "revision_id": db_entry.get('headRevisionId'),
                                "local_hash": local_hash,
                            })

                remaining_local = [s for s in footprint_files if s['filename'] not in matched_local]
                remaining_meta = {u: e for u, e in meta_lib.items() if u not in matched_meta}

                uploads = []
                for local in remaining_local:
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
                        "parsed": local.get('parsed'),
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
            print("Footprints in library", lib_filename, "analyzed:")
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
        print('Syncing footprints ...')
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
                if t in (ActionType.Download, ActionType.UpdateLocal):
                    self.__downloadFootprint(sync_action['file'], sync_action['id'], lib_filename)
                    meta[self._meta_key][lib_filename][sync_action['uuid']] = metaEntry(
                        sync_action['file'],
                        sync_action['file_hash'],
                        sync_action.get('revision_id'),
                        self._contentHash(sync_action['file'], lib_filename),
                    )
                    prog_txt = "downloaded" if t == ActionType.Download else "updated locally"
                elif t == ActionType.DeleteLocal:
                    self.__deleteLocalFootprint(sync_action['file'], lib_filename)
                    if sync_action.get('uuid'):
                        meta[self._meta_key][lib_filename].pop(sync_action['uuid'], None)
                    prog_txt = "deleted"
                elif t == ActionType.RenameLocal:
                    self.__renameLocalFootprint(sync_action['file'], sync_action['new_name'], lib_filename)
                    meta[self._meta_key][lib_filename][sync_action['uuid']] = metaEntry(
                        sync_action['new_name'],
                        sync_action['file_hash'],
                        sync_action.get('revision_id'),
                        self._contentHash(sync_action['new_name'], lib_filename),
                    )
                    prog_txt = "renamed locally"
                elif t in (ActionType.Upload, ActionType.UpdateRemote, ActionType.DeleteRemote, ActionType.RenameRemote):
                    rc = self.__buildRemoteChange(sync_action, lib_dir, meta)
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

        print("Footprints synchronized (local); remote changes:", len(remote_changes))
        return remote_changes

    def __buildRemoteChange(self, sync_action, lib_dir, meta):
        t = sync_action['type']
        library_file_id = sync_action.get('library_file_id') or lib_dir['id']
        lib_filename = lib_dir['filename']

        if t == ActionType.DeleteRemote:
            return RemoteChange({
                "entity": "footprint",
                "op": "delete",
                "uuid": sync_action['uuid'],
                "expectedHash": sync_action.get('expected_hash') or sync_action.get('file_hash'),
            }, summary=f"delete footprint {sync_action.get('file')}", library_filename=lib_filename)

        if t == ActionType.RenameRemote:
            return RemoteChange({
                "entity": "footprint",
                "op": "rename",
                "uuid": sync_action['uuid'],
                "expectedHash": sync_action.get('expected_hash') or sync_action.get('file_hash'),
                "name": sync_action['file'],
                "libraryFileId": library_file_id,
            }, summary=f"rename footprint {sync_action.get('old_name')} -> {sync_action['file']}", library_filename=lib_filename)

        built = self.__prepareFootprintPayload(sync_action['file'], library_file_id, lib_filename, meta)
        if built is None:
            return None
        change, blobs = built
        if t == ActionType.Upload:
            change['op'] = 'create'
        else:
            change['op'] = 'update'
            change['uuid'] = sync_action['uuid']
            change['expectedHash'] = sync_action.get('expected_hash') or sync_action.get('file_hash')
        return RemoteChange(change, blobs, summary=f"{change['op']} footprint {sync_action['file']}", library_filename=lib_filename)

    def __prepareFootprintPayload(self, filename, library_file_id, library_name, meta):
        library_dir = Path(self._config['output_path'] + '/' + self._directory + '/' + library_name + '.pretty')
        file = library_dir / (filename + ".kicad_mod")
        try:
            with open(file, 'r', encoding='utf-8') as f:
                file_data = f.read()
        except Exception:
            return None

        parsed_data = loads(file_data)
        attrs = getSymbolValue(parsed_data, 'attr')
        attributes = attrs[0][1:] if attrs else []

        fp_type = 0 if Symbol('smd') in attributes else 1
        board_only = ("board_only" in attributes) or (Symbol('board_only') in attributes)
        exclude_from_pos_files = ("exclude_from_pos_files" in attributes) or (Symbol('exclude_from_pos_files') in attributes)
        exclude_from_bom = ("exclude_from_bom" in attributes) or (Symbol('exclude_from_bom') in attributes)

        layer = getSymbolValue(parsed_data, 'layer')
        layer = layer[0][1] if layer else ""
        description = getSymbolValue(parsed_data, 'descr')
        description = description[0][1] if description else ""
        tags = getSymbolValue(parsed_data, 'tags')
        tags = tags[0][1] if tags else ""

        canonical = canonicalFootprintText(parsed_data)
        blob_hash = sha256Text(canonical)

        # ALL models
        extracted = extractModels(parsed_data)
        models_payload = []
        for m in extracted:
            uuid = self._resolveModel3dUuid(meta, m['directory'], m['filename'])
            if uuid is None:
                print(
                    "Warning: unknown 3D model '",
                    filePathKey(m['directory'], m['filename']),
                    "' – model entry not transferred (path kept in text)",
                )
                continue
            entry = {
                "position": m['position'],
                "model3dUuid": uuid,
                "offset": m['offset'],
                "scale": m['scale'],
                "rotate": m['rotate'],
                "hide": m['hide'],
            }
            if m.get('opacity') is not None:
                entry['opacity'] = m['opacity']
            models_payload.append(entry)

        preview = self.__getPreviewImage(library_dir, filename)
        blobs = [{"hash": blob_hash, "bytes": canonical.encode('utf-8'), "media_type": MEDIA_SEXPR}]
        change = {
            "entity": "footprint",
            "blobHash": blob_hash,
            "libraryFileId": library_file_id,
            "name": filename,
            "type": fp_type,
            "boardOnly": board_only,
            "excludeFromPosFiles": exclude_from_pos_files,
            "excludeFromBom": exclude_from_bom,
            "height": 0.0,
            "layer": layer,
            "description": description,
            "tags": tags,
            "property": "",
            "models": models_payload,
        }
        if preview:
            preview_hash = sha256Text(preview)
            blobs.append({"hash": preview_hash, "bytes": preview.encode('utf-8'), "media_type": MEDIA_SVG})
            change["previewBlobHash"] = preview_hash
        return change, blobs

    def _contentHash(self, filename, library_name):
        file = Path(self._config['output_path'] + '/' + self._directory + '/' + library_name + '.pretty') / (filename + ".kicad_mod")
        if not file.is_file():
            return None
        try:
            text = canonicalFootprintText(loads(file.read_text(encoding='utf-8')))
        except Exception:
            return None
        return sha256Text(text)

    def __downloadFootprint(self, filename, footprint_id, library_name):
        print('Downloading footprint: ' + filename)
        try:
            entry_data = self._api.get(footprint_id)
        except Exception:
            return ReturnCode.NoConnection

        data = entry_data.get('data') or ''
        # Rewrite model paths by position using parse/setModelPaths, then serialise.
        # Paths are normalised back to PLACEHOLDER during check hashing.
        parsed_data = loads(data)
        models = entry_data.get('models') or []
        paths_by_position = {}
        prefix = self._modelPathPrefix()
        for m in models:
            directory = (m.get('directory') or '').replace('\\', '/').strip('/')
            fname = m.get('filename') or ''
            if directory:
                paths_by_position[int(m.get('position', 0))] = f"{prefix}/{directory}/{fname}"
            else:
                paths_by_position[int(m.get('position', 0))] = f"{prefix}/{fname}"
        if paths_by_position:
            setModelPaths(parsed_data, paths_by_position)

        file = Path(self._config['output_path'] + '/' + self._directory + '/' + library_name + '.pretty') / (filename + ".kicad_mod")
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            # Write canonical-with-local-paths: dumps then replace PLACEHOLDER if any remain
            text = dumps(parsed_data, pretty_print=True)
            text = text.replace('${PLACEHOLDER}/', prefix + '/')
            if not text.endswith('\n'):
                text += '\n'
            with open(file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
        except Exception:
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __deleteLocalFootprint(self, filename, library_name):
        print('Delete local footprint: ' + filename)
        file = Path(self._config['output_path'] + '/' + self._directory + '/' + library_name + '.pretty') / (filename + ".kicad_mod")
        try:
            if os.path.exists(file):
                os.remove(file)
        except Exception:
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __renameLocalFootprint(self, old_name, new_name, library_name):
        print('Rename local footprint:', old_name, '->', new_name)
        lib = Path(self._config['output_path'] + '/' + self._directory + '/' + library_name + '.pretty')
        old = lib / (old_name + ".kicad_mod")
        new = lib / (new_name + ".kicad_mod")
        try:
            with open(old, 'r', encoding='utf-8') as f:
                parsed = loads(f.read())
            # footprint name is 2nd element
            if isinstance(parsed, list) and len(parsed) >= 2:
                parsed[1] = new_name
            with open(new, 'w', encoding='utf-8', newline='\n') as f:
                text = dumps(parsed, pretty_print=True)
                if not text.endswith('\n'):
                    text += '\n'
                f.write(text)
            os.remove(old)
        except Exception as e:
            print('Rename failed:', e)
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __getPreviewImage(self, library_path, footprint_name):
        file_data = ""
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            cmd = [
                getKiCadCliPath(), "fp", "export", "svg",
                "--layers", "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,F.Fab,B.Fab,User.Drawings,User.Comments,Margin,F.Courtyard,B.Courtyard",
                "--output", tmp_dir_name,
                "--footprint", footprint_name,
                library_path.as_posix(),
            ]
            CREATE_NO_WINDOW = 0x08000000
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            except OSError as e:
                print("Error running kicad-cli for preview image of footprint '", footprint_name, "':", e, file=sys.stderr)
                return file_data
            if result.returncode == 0:
                output_file = tmp_dir_name + "/" + footprint_name + ".svg"
                self.__fixFootprintColor(output_file)
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        file_data = f.read()
                except Exception:
                    file_data = ""
            else:
                print("Error exporting preview image for footprint '", footprint_name, "':", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
        return file_data

    def __fixFootprintColor(self, footprint_image):
        color_map = {
            "#37CBCB": "#C83434", "#B2803A": "#4D7FC4", "#7AFF7A": "#840084",
            "#FFFF7A": "#000084", "#4A5F65": "#B4A09A", "#FF3D3D": "#00C2C2",
            "#0D115E": "#F2EDA1", "#174D58": "#E8B2A7", "#279B00": "#56327b",
            "#FD0010": "#007175", "#3D3D3D": "#C2C2C2", "#A66A22": "#5994DC",
            "#4A242D": "#B4DBD2", "#2737AD": "#D8C852", "#2F2D31": "#D0D2CD",
            "#00D91D": "#FF26E2", "#D91600": "#26E9FF", "#505050": "#AFAFAF",
            "#A7A27A": "#585D84",
        }
        try:
            with open(footprint_image, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                for old_color, new_color in color_map.items():
                    lines[i] = lines[i].replace(old_color, new_color)
            with open(footprint_image, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        except Exception:
            pass
