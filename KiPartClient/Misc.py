import glob
import hashlib
import os
import shutil
import sys
from enum import Enum
from .sexpdata import Symbol


######################################################################################


_kicad_cli_path = None

def getKiCadCliPath():
    """Locate kicad-cli, which is usually not on PATH on Windows."""
    global _kicad_cli_path
    if _kicad_cli_path is not None:
        return _kicad_cli_path

    exe_name = "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
    candidates = []

    # KiCad's own bin directory when running inside KiCad or with KiCad's python
    candidates.append(os.path.join(os.path.dirname(sys.executable), exe_name))
    try:
        import pcbnew
        # <KiCad>/bin/Lib/site-packages/pcbnew.py
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(pcbnew.__file__)), "..", "..", exe_name))
    except Exception:
        pass

    on_path = shutil.which("kicad-cli")
    if on_path:
        candidates.append(on_path)

    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        installed = glob.glob(os.path.join(program_files, "KiCad", "*", "bin", exe_name))
        candidates += sorted(installed, key = lambda p: [int(x) if x.isdigit() else 0 for x in os.path.basename(os.path.dirname(os.path.dirname(p))).split(".")], reverse = True)

    for candidate in candidates:
        if os.path.isfile(candidate):
            _kicad_cli_path = os.path.normpath(candidate)
            return _kicad_cli_path

    # fall back to PATH lookup by the OS
    return "kicad-cli"


######################################################################################


ActionType = Enum('ActionType', [
    'Download', 'Upload', 'DeleteRemote', 'DeleteLocal',
    'UpdateRemote', 'UpdateLocal', 'Conflict',
    'RenameLocal', 'RenameRemote',
])


######################################################################################


class RemoteChange:
    """A pending remote commit change plus optional blobs to upload first."""

    def __init__(self, change, blobs=None, summary=None, library_filename=None):
        self.change = change  # dict shaped for POST /api/commit changes[]
        self.blobs = blobs or []  # [{hash, bytes, media_type}, ...]
        self.summary = summary or _defaultSummary(change)
        # Not part of the commit payload. Needed to record creates in .kipart_sync,
        # because the commit result does not include the library filename.
        self.library_filename = library_filename


def _defaultSummary(change):
    entity = change.get('entity', '?')
    op = change.get('op', '?')
    name = change.get('name') or change.get('filename') or change.get('uuid') or ''
    return f"{op} {entity} {name}".strip()


######################################################################################


ReturnCode = Enum('ErrorCode', ['OK', 'NoConnection', 'FileWriteError', 'FileReadError', 'Unknown'])


######################################################################################


def calculate_sha256(file_path):
    # Create a sha256 hash object
    sha256_hash = hashlib.sha256()

    # Open the file in binary mode
    with open(file_path, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    # Return the hexadecimal digest of the hash
    return sha256_hash.hexdigest()


######################################################################################


def calculate_sha256_from_string(data):
    # Return the hexadecimal digest of the hash
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


######################################################################################


def getSymbolValue(sExpObject, symbol):
    out_val = []

    for index, elem in enumerate(sExpObject):
        # if element is the searched symbol => output rest of list
        if isinstance(elem, Symbol) and elem == Symbol(symbol):
            if len(sExpObject) > (index + 1):
                out_val.append(sExpObject[index:])
            else:
                out_val.append("")
        
        # if element is a list => check symbol in the first place of the sub list
        if type(elem) is list:
            # if sub list starts with searched symbol => output rest of sub list
            if isinstance(elem[0], Symbol) and elem[0] == Symbol(symbol):
                if len(elem) > 1:
                    out_val.append(elem)
                else:
                    out_val.append("")
                
    return out_val


######################################################################################


def setSymbolValue(sExpObject, symbol, new_value):

    # loop through sExpObject and replace symbol with new_value
    for index, elem in enumerate(sExpObject):
        # if element is the searched symbol => replace it with new_value
        if isinstance(elem, Symbol) and elem == Symbol(symbol):
            sExpObject[index] = new_value
        
        # if element is a list => check symbol in the first place of the sub list
        if type(elem) is list:
            # if sub list starts with searched symbol => replace it with new_value
            if isinstance(elem[0], Symbol) and elem[0] == Symbol(symbol):
                if len(elem) > 1:
                    elem[1] = new_value

    return sExpObject


# setModelPaths lives in Canonical (used for multi-model footprints); re-export for convenience
def setModelPaths(parsed, paths_by_position):
    from .Canonical import setModelPaths as _set
    return _set(parsed, paths_by_position)


######################################################################################


def convertBackendToFrontend(check_data, finished = False, stopped = False):
    tmp = {
        "finished": finished,
        "stopped": stopped,        

        "cntNew": check_data["cntNew"],
        "cntChanged": check_data["cntChanged"],
        "cntDeleted": check_data["cntDeleted"],
        "cntConflict": check_data["cntConflict"],
        "cntUnchanged": check_data["cntUnchanged"],

        "newList": [],
        "changedList": [],
        "deletedList": [],
        "conflictList": []
    }

    action_map = {
        ActionType.Download: tmp["newList"],
        ActionType.Upload: tmp["newList"],
        ActionType.UpdateRemote: tmp["changedList"],
        ActionType.UpdateLocal: tmp["changedList"],
        ActionType.DeleteRemote: tmp["deletedList"],
        ActionType.DeleteLocal: tmp["deletedList"],
        ActionType.Conflict: tmp["conflictList"],
        ActionType.RenameLocal: tmp["changedList"],
        ActionType.RenameRemote: tmp["changedList"],
    }

    

    for key in check_data:
        if isinstance(check_data[key], list):
            for actions in check_data[key]:
                for action in actions["sync_actions"]:
                    action_map[action["type"]].append(action["filename"])

    return tmp