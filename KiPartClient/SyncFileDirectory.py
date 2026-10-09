import os
import datetime
from pathlib import Path
from collections import Counter

from .Misc import ActionType, ReturnCode, RemoteChange, calculate_sha256
from .ChangeReview import resolve_action
from .RestAPI import RestAPI
from .Canonical import filePathKey, sha256Bytes
from .MetaFile import load as loadMeta, save as saveMeta, ensureV2


_MEDIA_TYPES = {
    'model3d': 'model/step',
    'datasheet': 'application/pdf',
    'template': 'application/octet-stream',
}


class SyncFileDirectory:
    def __init__(self, config, directory, api_name):
        self._config = config
        self._directory = directory
        self._api_name = api_name
        self._api = RestAPI(self._config, self._api_name)

    def _normalizeOutputPath(self):
        if not self._config['output_path'].startswith('/') and not (self._config['output_path'][1] == ":"):
            self._config['output_path'] = os.path.dirname(__file__) + '/' + self._config['output_path']

    def _serverHash(self, entry):
        return entry.get('hash') or entry.get('fileHash')

    def _entryPath(self, entry):
        return filePathKey(entry.get('directory'), entry.get('filename'))

    def check(self):
        print('Checking ' + self._api_name + ' ...')
        self._normalizeOutputPath()
        meta = ensureV2(self._config['output_path'], self._api, self._config)
        meta_data = dict(meta.get(self._api_name) or {})

        read_path = Path(self._config['output_path'] + '/' + self._directory)
        if not read_path.exists():
            os.makedirs(read_path)

        local_files = []
        for file in read_path.rglob('*'):
            if file.is_file():
                relative = file.relative_to(read_path)
                directory = str(relative.parent).replace('\\', '/')
                if directory == '.':
                    directory = ''
                path_key = filePathKey(directory, file.name)
                local_files.append({
                    "filename": file.name,
                    "path": directory,
                    "path_key": path_key,
                    "file_hash": calculate_sha256(file),
                    "full_path": file,
                })

        num_all = len(local_files)
        local_by_path = {f['path_key']: f for f in local_files}
        db_entries = self._api.getList()

        sync_actions = []
        matched_local = set()
        matched_meta = set()

        for db_entry in db_entries:
            uuid = str(db_entry['uuid'])
            path_key = self._entryPath(db_entry)
            server_hash = self._serverHash(db_entry)
            meta_entry = meta_data.get(uuid)
            local = None
            if meta_entry:
                local = local_by_path.get(meta_entry.get('path') or path_key)
            if local is None:
                local = local_by_path.get(path_key)

            directory = (db_entry.get('directory') or '').rstrip('/')
            filename = db_entry.get('filename')

            if meta_entry is None and local is None:
                sync_actions.append({
                    "type": ActionType.Download,
                    "file": filename, "path": directory, "path_key": path_key,
                    "uuid": uuid, "id": db_entry['id'],
                    "file_hash": server_hash, "revision_id": db_entry.get('headRevisionId'),
                })
            elif meta_entry is not None and local is None:
                sync_actions.append({
                    "type": ActionType.DeleteRemote,
                    "file": filename, "path": directory, "path_key": path_key,
                    "uuid": uuid, "id": db_entry['id'],
                    "file_hash": meta_entry.get('hash') or server_hash,
                    "expected_hash": meta_entry.get('hash') or server_hash,
                })
                matched_meta.add(uuid)
            elif meta_entry is None and local is not None:
                sync_actions.append({
                    "type": ActionType.Conflict,
                    "file": filename, "path": directory, "path_key": path_key,
                    "uuid": uuid, "id": db_entry['id'],
                    "comment": f"Local and remote version of {self._api_name} are new",
                    "server_hash": server_hash,
                    "revision_id": db_entry.get('headRevisionId'),
                    "local_hash": local['file_hash'],
                    "full_path": local['full_path'],
                })
                matched_local.add(local['path_key'])
            else:
                matched_meta.add(uuid)
                matched_local.add(local['path_key'])
                meta_hash = meta_entry.get('hash')
                local_hash = local['file_hash']
                if meta_hash != server_hash and meta_hash == local_hash:
                    sync_actions.append({
                        "type": ActionType.UpdateLocal,
                        "file": filename, "path": directory, "path_key": path_key,
                        "uuid": uuid, "id": db_entry['id'],
                        "file_hash": server_hash, "revision_id": db_entry.get('headRevisionId'),
                    })
                elif meta_hash == server_hash and meta_hash != local_hash:
                    sync_actions.append({
                        "type": ActionType.UpdateRemote,
                        "file": local['filename'], "path": local['path'], "path_key": local['path_key'],
                        "uuid": uuid, "id": db_entry['id'],
                        "file_hash": local_hash, "expected_hash": server_hash,
                        "full_path": local['full_path'],
                    })
                elif meta_hash != server_hash and meta_hash != local_hash:
                    sync_actions.append({
                        "type": ActionType.Conflict,
                        "file": filename, "path": directory, "path_key": path_key,
                        "uuid": uuid, "id": db_entry['id'],
                        "comment": f"Local and remote version of {self._api_name} have changed!",
                        "server_hash": server_hash,
                        "revision_id": db_entry.get('headRevisionId'),
                        "local_hash": local_hash,
                        "full_path": local['full_path'],
                    })

        remaining_local = [f for f in local_files if f['path_key'] not in matched_local]
        remaining_meta = {u: e for u, e in meta_data.items() if u not in matched_meta}

        for local in remaining_local:
            meta_uuid = None
            for u, e in list(remaining_meta.items()):
                if e.get('path') == local['path_key']:
                    meta_uuid = u
                    break
            if meta_uuid is not None:
                sync_actions.append({
                    "type": ActionType.DeleteLocal,
                    "file": local['filename'], "path": local['path'], "path_key": local['path_key'],
                    "uuid": meta_uuid,
                })
                remaining_meta.pop(meta_uuid, None)
            else:
                sync_actions.append({
                    "type": ActionType.Upload,
                    "file": local['filename'], "path": local['path'], "path_key": local['path_key'],
                    "file_hash": local['file_hash'], "full_path": local['full_path'],
                })

        for u, e in remaining_meta.items():
            directory, filename = '', e.get('path', '')
            if '/' in (e.get('path') or ''):
                directory, filename = e['path'].rsplit('/', 1)
            sync_actions.append({
                "type": ActionType.DeleteLocal,
                "file": filename, "path": directory, "path_key": e.get('path'),
                "uuid": u,
            })

        action_counts = Counter(a['type'] for a in sync_actions)
        print(self._directory + " analyzed:")
        print("Download:", action_counts[ActionType.Download])
        print("Upload:", action_counts[ActionType.Upload])
        print("Delete:", action_counts[ActionType.DeleteRemote] + action_counts[ActionType.DeleteLocal])
        print("Update:", action_counts[ActionType.UpdateRemote] + action_counts[ActionType.UpdateLocal])
        print("Conflict:", action_counts[ActionType.Conflict])

        sync_data = {
            "cntNew": action_counts[ActionType.Download] + action_counts[ActionType.Upload],
            "cntChanged": action_counts[ActionType.UpdateRemote] + action_counts[ActionType.UpdateLocal],
            "cntDeleted": action_counts[ActionType.DeleteRemote] + action_counts[ActionType.DeleteLocal],
            "cntConflict": action_counts[ActionType.Conflict],
            "cntUnchanged": max(0, num_all + action_counts[ActionType.Download] - len(sync_actions)),
            "sync_actions": sync_actions,
        }
        return sync_data

    def sync(self, sync_actions, sub_progress_callback):
        print('Syncing ' + self._api_name + ' ...')
        self._normalizeOutputPath()
        meta = loadMeta(self._config['output_path'])
        meta.setdefault(self._api_name, {})
        remote_changes = []

        if len(sync_actions) > 0:
            sub_progress_callback(True, False, "", len(sync_actions))

        prog_cnt = 0
        for sync_action in sync_actions:
            prog_txt = ""
            resolved = resolve_action(sync_action)
            if resolved is None:
                prog_cnt += 1
                sub_progress_callback(False, False, sync_action.get('file', '') + " ignored", prog_cnt)
                continue
            sync_action = resolved
            t = sync_action['type']
            if t in (ActionType.Download, ActionType.UpdateLocal):
                self.__downloadFile(sync_action)
                meta[self._api_name][sync_action['uuid']] = {
                    'path': sync_action.get('path_key') or filePathKey(sync_action.get('path'), sync_action.get('file')),
                    'hash': sync_action['file_hash'],
                    'revision_id': sync_action.get('revision_id'),
                }
                prog_txt = "downloaded" if t == ActionType.Download else "updated locally"
            elif t == ActionType.DeleteLocal:
                self.__deleteLocalFile(sync_action)
                if sync_action.get('uuid'):
                    meta[self._api_name].pop(sync_action['uuid'], None)
                prog_txt = "deleted"
            elif t in (ActionType.Upload, ActionType.UpdateRemote, ActionType.DeleteRemote):
                rc = self.__buildRemoteChange(sync_action)
                if rc is not None:
                    remote_changes.append(rc)
                prog_txt = "queued for commit"
            elif t == ActionType.Conflict:
                prog_txt = "conflict (skipped)"

            prog_cnt += 1
            sub_progress_callback(False, False, sync_action.get('file', '') + " " + prog_txt, prog_cnt)

        meta["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f %z')
        saveMeta(self._config['output_path'], meta)

        if len(sync_actions) > 0:
            sub_progress_callback(False, True, "", 0)

        print(self._directory + " synchronized (local); remote changes:", len(remote_changes))
        return remote_changes

    def __buildRemoteChange(self, sync_action):
        t = sync_action['type']
        if t == ActionType.DeleteRemote:
            return RemoteChange({
                "entity": self._api_name,
                "op": "delete",
                "uuid": sync_action['uuid'],
                "expectedHash": sync_action.get('expected_hash') or sync_action.get('file_hash'),
            }, summary=f"delete {self._api_name} {sync_action.get('path_key') or sync_action.get('file')}")

        directory = sync_action.get('path') or ''
        # store directory with trailing slash to match existing server convention when non-empty
        directory_for_api = directory
        if directory_for_api and not directory_for_api.endswith('/'):
            # Prefer no trailing slash for new creates; server accepts either.
            # Existing data uses trailing slash — keep without for new uploads (cleaner).
            pass
        filename = sync_action['file']
        full_path = sync_action.get('full_path')
        if full_path is None:
            full_path = Path(self._config['output_path']) / self._directory / directory / filename
        try:
            with open(full_path, 'rb') as f:
                data = f.read()
        except Exception:
            return None
        blob_hash = sha256Bytes(data)
        media = _MEDIA_TYPES.get(self._api_name, 'application/octet-stream')
        # guess step/wrl vs pdf by extension
        ext = Path(filename).suffix.lower()
        if ext in ('.step', '.stp'):
            media = 'model/step'
        elif ext == '.wrl':
            media = 'model/vrml'
        elif ext == '.pdf':
            media = 'application/pdf'

        change = {
            "entity": self._api_name,
            "blobHash": blob_hash,
            "directory": directory_for_api,
            "filename": filename,
        }
        if t == ActionType.Upload:
            change['op'] = 'create'
        else:
            change['op'] = 'update'
            change['uuid'] = sync_action['uuid']
            change['expectedHash'] = sync_action.get('expected_hash') or sync_action.get('file_hash')

        return RemoteChange(
            change,
            [{"hash": blob_hash, "bytes": data, "media_type": media}],
            summary=f"{change['op']} {self._api_name} {filePathKey(directory, filename)}",
        )

    def __downloadFile(self, sync_action):
        directory = sync_action.get('path') or ''
        filename = sync_action['file']
        blob_hash = sync_action.get('file_hash')
        print('Download ' + self._api_name + ': ' + filePathKey(directory, filename))

        base = Path(self._config['output_path']) / self._directory
        target_dir = base / directory if directory else base
        target_dir.mkdir(parents=True, exist_ok=True)

        # Prefer blob download; fall back to detail.hash
        try:
            if not blob_hash:
                entry = self._api.get(sync_action['id'])
                blob_hash = entry.get('hash') or entry.get('fileHash')
            data = self._api.getBlob(blob_hash)
        except Exception:
            return ReturnCode.NoConnection

        try:
            with open(target_dir / filename, 'wb') as f:
                f.write(data)
        except Exception:
            return ReturnCode.FileWriteError
        return ReturnCode.OK

    def __deleteLocalFile(self, sync_action):
        directory = sync_action.get('path') or ''
        filename = sync_action['file']
        print('Delete ' + self._api_name + ': ' + filePathKey(directory, filename))
        path = Path(self._config['output_path']) / self._directory / directory / filename
        try:
            if path.exists():
                path.unlink()
            if directory:
                dir_path = Path(self._config['output_path']) / self._directory / directory
                if dir_path.is_dir() and not any(dir_path.iterdir()):
                    dir_path.rmdir()
        except Exception:
            return ReturnCode.FileWriteError
        return ReturnCode.OK
