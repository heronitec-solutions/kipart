"""Load/save .kipart_sync v2 and migrate from v1."""

import datetime
import json
import os
import shutil
from pathlib import Path

from .Canonical import filePathKey, sha256Bytes, sha256Text, canonicalSymbolText, canonicalFootprintText
from .sexpdata import loads


def emptyMeta(last_commit_id=None):
    return {
        "meta_version": 2,
        "last_sync": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f %z'),
        "last_commit_id": last_commit_id,
        "symbols": {},
        "footprints": {},
        "model3d": {},
        "datasheet": {},
        "template": {},
    }


def metaPath(output_path):
    return Path(output_path) / '.kipart_sync'


def load(output_path):
    path = metaPath(output_path)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save(output_path, meta):
    path = metaPath(output_path)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=4)


def ensureV2(output_path, api, config):
    """Load meta; migrate v1→v2 if needed. Returns meta dict."""
    meta = load(output_path)
    version = meta.get('meta_version')
    if version is None or version == 1 or isinstance(meta.get('symbols'), list):
        meta = migrateV1(meta, api, config)
        save(output_path, meta)
    return meta


def _serverHash(entry):
    return entry.get('hash') or entry.get('fileHash')


def _findLocalSymbolCanonicalText(config, lib_filename, name):
    from .SymbolLibraryDir import SYMBOL_LIB_EXTENSION, findSymbol
    lib_path = Path(config['output_path']) / 'Symbols' / (lib_filename + SYMBOL_LIB_EXTENSION)
    try:
        entry = findSymbol(lib_path, name)
    except Exception:
        return None
    if entry is None:
        return None
    return canonicalSymbolText(entry['data'])


def _findLocalSymbolHash(config, lib_filename, name):
    text = _findLocalSymbolCanonicalText(config, lib_filename, name)
    return sha256Text(text) if text is not None else None


def _findLocalFootprintCanonicalText(config, lib_filename, name):
    file = Path(config['output_path']) / 'Footprints' / (lib_filename + '.pretty') / (name + '.kicad_mod')
    if not file.is_file():
        return None
    try:
        with open(file, 'r', encoding='utf-8') as f:
            parsed = loads(f.read())
        return canonicalFootprintText(parsed)
    except Exception:
        return None


def _findLocalFootprintHash(config, lib_filename, name):
    text = _findLocalFootprintCanonicalText(config, lib_filename, name)
    return sha256Text(text) if text is not None else None


def _findLocalFileHash(config, subdir, path_key):
    file = Path(config['output_path']) / subdir / path_key
    if not file.is_file():
        return None
    try:
        with open(file, 'rb') as f:
            return sha256Bytes(f.read())
    except Exception:
        return None


CANONICALIZE_COMMIT_MESSAGE = "Canonicalize library content after migration to API v2"


def metaEntry(name, server_hash, revision_id=None, content_hash=None):
    """Meta record for one symbol or footprint.

    hash is the server blob hash. content_hash is the local canonical hash that
    corresponds to that blob. They differ when the server still stores the
    original text (no trailing newline, ${LIB} model paths, KiCad formatting)
    while the client hashes the canonical form.
    """
    entry = {'name': name, 'hash': server_hash}
    if revision_id is not None:
        entry['revision_id'] = revision_id
    if content_hash:
        entry['content_hash'] = content_hash
    return entry


def classifyContent(meta_entry, server_hash, local_hash):
    """
    Return (state, meta_dirty).

    state is 'unchanged', 'server', 'local', or 'conflict'.
    A file is unchanged when its canonical hash still matches the hash recorded
    for this server blob, even if that blob is not itself canonical.
    """
    dirty = False
    blob = meta_entry.get('hash')
    content = meta_entry.get('content_hash') or blob

    if local_hash and local_hash == server_hash:
        if blob != server_hash:
            meta_entry['hash'] = server_hash
            dirty = True
        if meta_entry.get('content_hash') != server_hash:
            meta_entry['content_hash'] = server_hash
            dirty = True
        return 'unchanged', dirty

    server_changed = blob != server_hash
    local_changed = content != local_hash
    if server_changed and local_changed:
        return 'conflict', dirty
    if server_changed:
        return 'server', dirty
    if local_changed:
        return 'local', dirty
    return 'unchanged', dirty


def reconcileCanonicalAfterMigration(meta, api, config):
    """
    Remember when local canonical text matches the server blob even though the
    hashes differ (trailing newline, model path variable, pretty-print).

    Those files are in sync. They are not queued for upload.
    """
    pending = list(meta.get('_pending_canonicalize') or [])
    pending_uuids = {str(p.get('uuid')) for p in pending}
    changed = False

    def _remember(info, uuid, server_hash, local_hash):
        nonlocal pending, pending_uuids, changed
        info['hash'] = server_hash
        info['content_hash'] = local_hash
        if uuid in pending_uuids:
            pending = [p for p in pending if str(p.get('uuid')) != uuid]
            pending_uuids.discard(uuid)
        changed = True

    # --- symbols ---
    symbol_api = api.__class__(config, 'symbol')
    try:
        all_symbols = symbol_api.getList()
    except Exception:
        all_symbols = []
    symbols_by_uuid = {str(s.get('uuid')): s for s in all_symbols}

    for lib_filename, entries in list((meta.get('symbols') or {}).items()):
        for uuid, info in list(entries.items()):
            uuid = str(uuid)
            server = symbols_by_uuid.get(uuid)
            if server is None:
                continue
            server_hash = _serverHash(server)
            name = info.get('name') or server.get('name')
            local_text = _findLocalSymbolCanonicalText(config, lib_filename, name)
            if local_text is None or not server_hash:
                continue
            local_hash = sha256Text(local_text)
            if info.get('hash') == server_hash and info.get('content_hash') == local_hash:
                if uuid in pending_uuids:
                    pending = [p for p in pending if str(p.get('uuid')) != uuid]
                    pending_uuids.discard(uuid)
                    changed = True
                continue
            if local_hash == server_hash:
                if uuid in pending_uuids:
                    pending = [p for p in pending if str(p.get('uuid')) != uuid]
                    pending_uuids.discard(uuid)
                    changed = True
                continue
            try:
                detail = symbol_api.get(server['id'])
            except Exception:
                continue
            data = detail.get('data')
            if not data:
                continue
            try:
                server_canonical = canonicalSymbolText(loads(data))
            except Exception:
                continue
            if server_canonical != local_text:
                continue
            _remember(info, uuid, server_hash, local_hash)

    # --- footprints ---
    fp_api = api.__class__(config, 'footprint')
    try:
        all_fps = fp_api.getList()
    except Exception:
        all_fps = []
    fps_by_uuid = {str(f.get('uuid')): f for f in all_fps}

    for lib_filename, entries in list((meta.get('footprints') or {}).items()):
        for uuid, info in list(entries.items()):
            uuid = str(uuid)
            server = fps_by_uuid.get(uuid)
            if server is None:
                continue
            server_hash = _serverHash(server)
            name = info.get('name') or server.get('name')
            local_text = _findLocalFootprintCanonicalText(config, lib_filename, name)
            if local_text is None or not server_hash:
                continue
            local_hash = sha256Text(local_text)
            if info.get('hash') == server_hash and info.get('content_hash') == local_hash:
                if uuid in pending_uuids:
                    pending = [p for p in pending if str(p.get('uuid')) != uuid]
                    pending_uuids.discard(uuid)
                    changed = True
                continue
            if local_hash == server_hash:
                if uuid in pending_uuids:
                    pending = [p for p in pending if str(p.get('uuid')) != uuid]
                    pending_uuids.discard(uuid)
                    changed = True
                continue
            try:
                detail = fp_api.get(server['id'])
            except Exception:
                continue
            data = detail.get('data')
            if not data:
                continue
            try:
                server_canonical = canonicalFootprintText(loads(data))
            except Exception:
                continue
            if server_canonical != local_text:
                continue
            _remember(info, uuid, server_hash, local_hash)

    if pending:
        meta['_pending_canonicalize'] = pending
    else:
        meta.pop('_pending_canonicalize', None)
    if changed:
        save(config['output_path'], meta)
    return pending


def clearPendingCanonicalize(meta, output_path, committed_uuids=None):
    """Remove pending canonicalize entries (all, or only those just committed)."""
    pending = meta.get('_pending_canonicalize') or []
    if committed_uuids is None:
        meta.pop('_pending_canonicalize', None)
    else:
        committed = {str(u) for u in committed_uuids}
        remaining = [p for p in pending if str(p.get('uuid')) not in committed]
        if remaining:
            meta['_pending_canonicalize'] = remaining
        else:
            meta.pop('_pending_canonicalize', None)
    save(output_path, meta)


def migrateV1(meta_v1, api, config):
    """
    Migrate v1 meta to v2. Backs up v1 as .kipart_sync.v1.bak.
    Base hash = server hash if local canonical hash == server hash, else keep v1 hash.
    """
    output_path = config['output_path']
    bak = Path(output_path) / '.kipart_sync.v1.bak'
    src = metaPath(output_path)
    if src.is_file() and not bak.exists():
        shutil.copy2(src, bak)

    info = None
    try:
        info = api.info()
    except Exception:
        pass

    meta = emptyMeta(last_commit_id=(info or {}).get('headCommitId'))
    meta['last_sync'] = meta_v1.get('last_sync') or meta['last_sync']

    # --- symbols: v1 list of {lib: [ {name: [hash, date]}, ... ]} ---
    for lib_block in meta_v1.get('symbols') or []:
        if not isinstance(lib_block, dict):
            continue
        for lib_filename, entries in lib_block.items():
            meta['symbols'].setdefault(lib_filename, {})
            # resolve library file id
            lib_id = None
            try:
                libs = api.__class__(config, 'libraryfile').getFilteredList('Type', '1')
                for lib in libs:
                    if lib.get('filename') == lib_filename:
                        lib_id = lib['id']
                        break
            except Exception:
                libs = []

            symbol_api = api.__class__(config, 'symbol')
            db_by_name = {}
            if lib_id is not None:
                try:
                    for e in symbol_api.getFilteredList('LibraryFileId', str(lib_id)):
                        db_by_name[e['name']] = e
                except Exception:
                    pass

            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                for name, value in entry.items():
                    v1_hash = value[0] if isinstance(value, list) and value else None
                    db = db_by_name.get(name)
                    if db is None:
                        continue
                    uuid = str(db['uuid'])
                    server_hash = _serverHash(db)
                    local_hash = _findLocalSymbolHash(config, lib_filename, name)
                    base_hash = server_hash if (local_hash is not None and local_hash == server_hash) else (v1_hash or server_hash)
                    meta['symbols'][lib_filename][uuid] = {
                        'name': name,
                        'hash': base_hash,
                        'revision_id': db.get('headRevisionId'),
                    }

    # --- footprints ---
    for lib_block in meta_v1.get('footprints') or []:
        if not isinstance(lib_block, dict):
            continue
        for lib_filename, entries in lib_block.items():
            meta['footprints'].setdefault(lib_filename, {})
            lib_id = None
            try:
                libs = api.__class__(config, 'libraryfile').getFilteredList('Type', '0')
                for lib in libs:
                    if lib.get('filename') == lib_filename:
                        lib_id = lib['id']
                        break
            except Exception:
                pass

            fp_api = api.__class__(config, 'footprint')
            db_by_name = {}
            if lib_id is not None:
                try:
                    for e in fp_api.getFilteredList('LibraryFileId', str(lib_id)):
                        db_by_name[e['name']] = e
                except Exception:
                    pass

            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                for name, value in entry.items():
                    v1_hash = value[0] if isinstance(value, list) and value else None
                    db = db_by_name.get(name)
                    if db is None:
                        continue
                    uuid = str(db['uuid'])
                    server_hash = _serverHash(db)
                    local_hash = _findLocalFootprintHash(config, lib_filename, name)
                    base_hash = server_hash if (local_hash is not None and local_hash == server_hash) else (v1_hash or server_hash)
                    meta['footprints'][lib_filename][uuid] = {
                        'name': name,
                        'hash': base_hash,
                        'revision_id': db.get('headRevisionId'),
                    }

    # --- files: model3d / datasheet / template ---
    subdirs = {
        'model3d': 'Packages3D',
        'datasheet': 'Datasheets',
        'template': 'Templates',
    }
    for entity, subdir in subdirs.items():
        file_api = api.__class__(config, entity)
        db_by_path = {}
        try:
            for e in file_api.getList():
                key = filePathKey(e.get('directory'), e.get('filename'))
                db_by_path[key] = e
                # also index with trailing-slash directory variant
                raw_dir = (e.get('directory') or '')
                if raw_dir.endswith('/'):
                    db_by_path[filePathKey(raw_dir, e.get('filename'))] = e
        except Exception:
            pass

        for entry in meta_v1.get(entity) or []:
            if not isinstance(entry, dict):
                continue
            for path_key, value in entry.items():
                v1_hash = value[0] if isinstance(value, list) and value else None
                norm = path_key.replace('\\', '/').lstrip('/')
                # strip trailing slash on directory part
                parts = norm.rsplit('/', 1)
                if len(parts) == 2:
                    norm = filePathKey(parts[0], parts[1])
                db = db_by_path.get(norm)
                if db is None:
                    # try with original
                    db = db_by_path.get(path_key)
                if db is None:
                    continue
                uuid = str(db['uuid'])
                server_hash = _serverHash(db)
                local_hash = _findLocalFileHash(config, subdir, norm)
                base_hash = server_hash if (local_hash is not None and local_hash == server_hash) else (v1_hash or server_hash)
                meta[entity][uuid] = {
                    'path': filePathKey(db.get('directory'), db.get('filename')),
                    'hash': base_hash,
                    'revision_id': db.get('headRevisionId'),
                }

    return meta
