#"C:\Users\<username>\AppData\Roaming\kicad\8.0\kicad_common.json"
#"C:\Users\<username>\AppData\Roaming\kicad\8.0\sym-lib-table"
#"C:\Users\<username>\AppData\Roaming\kicad\8.0\fp-lib-table"

import json
import os
import re
import sys
from .sexpdata import loads, dumps, Symbol

try:
    import pcbnew
except ImportError:  # outside KiCad (tests / CLI)
    pcbnew = None


LIB_TABLE_VERSION = 7
SYM_LIB_TABLE_TYPE = "sym_lib_table"
FP_LIB_TABLE_TYPE = "fp_lib_table"
CHAINED_TABLE_TYPE = "Table"
KIPART_VAR_SUFFIXES = ["3DMODEL_DIR", "BASE_PATH", "DATASHEET_DIR", "FOOTPRINT_DIR", "SYMBOL_DIR", "TEMPLATE_DIR"]


def GetKiCadVersion():
    if pcbnew is not None:
        version = pcbnew.GetMajorMinorVersion()
        major, minor = version.split('.')[:2]
        return f"{major}.{minor}"
    # Fallback for tests / CLI without pcbnew
    return os.environ.get('KICAD_VERSION', '10.0')


def _default_kicad_settings_dir(version, platform=None, environ=None, home=None):
    """KiCad user-settings directory when pcbnew cannot answer.

    Windows uses %APPDATA%\\kicad\\<version>. Linux uses
    $XDG_CONFIG_HOME/kicad/<version> (or ~/.config). macOS uses
    ~/Library/Preferences/kicad/<version>.
    """
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    if platform == "win32":
        base = environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, "kicad", version)
    if platform == "darwin":
        return os.path.join(home, "Library", "Preferences", "kicad", version)
    base = environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "kicad", version)


def GetKiCadSettingsDir():
    if pcbnew is not None:
        try:
            path = pcbnew.GetSettingsManager().GetUserSettingsPath()
            if path:
                return path
        except Exception:
            pass
    return _default_kicad_settings_dir(GetKiCadVersion())


def GetKiCadSettingsCommonSettingsFile():
    return os.path.join(GetKiCadSettingsDir(), "kicad_common.json")


def GetKiCadSymbolLibTableFile():
    return os.path.join(GetKiCadSettingsDir(), "sym-lib-table")


def GetKiCadFootprintLibTableFile():
    return os.path.join(GetKiCadSettingsDir(), "fp-lib-table")


def GetLocalSymbolLibTableFile(lib_base_path):
    return os.path.join(lib_base_path, "sym-lib-table")


def GetLocalFootprintLibTableFile(lib_base_path):
    return os.path.join(lib_base_path, "fp-lib-table")



def _getKiCadEnvVars(lib_path_key, lib_base_path):
    return {
        f"{lib_path_key}_3DMODEL_DIR": os.path.join(lib_base_path, "Packages3D"),
        f"{lib_path_key}_BASE_PATH": lib_base_path,
        f"{lib_path_key}_DATASHEET_DIR": os.path.join(lib_base_path, "Datasheets"),
        f"{lib_path_key}_FOOTPRINT_DIR": os.path.join(lib_base_path, "Footprints"),
        f"{lib_path_key}_SYMBOL_DIR": os.path.join(lib_base_path, "Symbols"),
        f"{lib_path_key}_TEMPLATE_DIR": os.path.join(lib_base_path, "Templates"),
    }


def _isSamePath(path_a, path_b):
    return os.path.normcase(os.path.normpath(str(path_a))) == os.path.normcase(os.path.normpath(str(path_b)))


def ensureKiCadEnvVars(lib_path_key, lib_base_path):
    """Add missing path variables of a library to KiCad's config and correct those pointing to a different path.

    Returns the names of the variables that were added or corrected.
    """
    config_file_path = GetKiCadSettingsCommonSettingsFile()

    with open(config_file_path, 'r') as json_file:
        data = json.load(json_file)

    if not isinstance(data.get("environment"), dict):
        data["environment"] = {}
    vars_dict = data["environment"].get("vars")
    if not isinstance(vars_dict, dict):
        vars_dict = {}

    changed = []
    for key, value in _getKiCadEnvVars(lib_path_key, lib_base_path).items():
        if key not in vars_dict:
            print(f"Adding missing path variable {key} = {value}")
        elif not _isSamePath(vars_dict[key], value):
            print(f"Correcting path variable {key}: {vars_dict[key]} -> {value}")
        else:
            continue
        vars_dict[key] = value
        changed.append(key)

    if changed:
        data["environment"]["vars"] = vars_dict
        with open(config_file_path, 'w') as json_file:
            json.dump(data, json_file, indent=4)

    return changed


def addKiCadEnvVars(lib_path_key, lib_base_path):
    config_file_path = GetKiCadSettingsCommonSettingsFile()

    with open(config_file_path, 'r') as json_file:
        data = json.load(json_file)

    vars_dict = data.get("environment", {}).get("vars", {})
    new_vars = _getKiCadEnvVars(lib_path_key, lib_base_path)

    if vars_dict is None:
        vars_dict = {}

    # Only add variables that are not already configured, never overwrite existing ones
    missing_vars = {key: value for key, value in new_vars.items() if key not in vars_dict}
    if not missing_vars:
        return False

    vars_dict.update(missing_vars)
    if not isinstance(data.get("environment"), dict):
        data["environment"] = {}
    data["environment"]["vars"] = vars_dict

    with open(config_file_path, 'w') as json_file:
        json.dump(data, json_file, indent=4)

    return True



def removeKiCadEnvVars(lib_path_key):
    config_file_path = GetKiCadSettingsCommonSettingsFile()

    with open(config_file_path, 'r') as json_file:
        data = json.load(json_file)

    vars_dict = data.get("environment", {}).get("vars", {})
    keys_to_remove = [
        f"{lib_path_key}_3DMODEL_DIR",
        f"{lib_path_key}_BASE_PATH",
        f"{lib_path_key}_DATASHEET_DIR",
        f"{lib_path_key}_FOOTPRINT_DIR",
        f"{lib_path_key}_SYMBOL_DIR",
        f"{lib_path_key}_TEMPLATE_DIR",
    ]

    # Remove the keys if they exist
    for key in keys_to_remove:
        vars_dict.pop(key, None)

    data["environment"]["vars"] = vars_dict

    with open(config_file_path, 'w') as json_file:
        json.dump(data, json_file, indent=4)



def renameKiCadEnvVars(lib_path_key_old, lib_path_key_new):
    config_file_path = GetKiCadSettingsCommonSettingsFile()

    with open(config_file_path, 'r') as json_file:
        data = json.load(json_file)

    vars_dict = data.get("environment", {}).get("vars", {})
    keys_to_rename = [
        "3DMODEL_DIR",
        "BASE_PATH",
        "DATASHEET_DIR",
        "FOOTPRINT_DIR",
        "SYMBOL_DIR",
        "TEMPLATE_DIR",
    ]

    # Rename the keys
    for suffix in keys_to_rename:
        old_key = f"{lib_path_key_old}_{suffix}"
        new_key = f"{lib_path_key_new}_{suffix}"
        if old_key in vars_dict:
            vars_dict[new_key] = vars_dict.pop(old_key)

    data["environment"]["vars"] = vars_dict

    with open(config_file_path, 'w') as json_file:
        json.dump(data, json_file, indent=4)



def updateKiCadEnvVars(lib_path_key, lib_base_path):
    config_file_path = GetKiCadSettingsCommonSettingsFile()

    with open(config_file_path, 'r') as json_file:
        data = json.load(json_file)

    vars_dict = data.get("environment", {}).get("vars", {})
    keys_to_update = _getKiCadEnvVars(lib_path_key, lib_base_path)

    # Update the base path for the keys
    for key, new_value in keys_to_update.items():
        if key in vars_dict:
            vars_dict[key] = new_value

    data["environment"]["vars"] = vars_dict

    with open(config_file_path, 'w') as json_file:
        json.dump(data, json_file, indent=4)



def _getLibraryEntryValue(entry, key):
    for field in entry[1:]:
        if isinstance(field, list) and len(field) >= 2 and field[0] == Symbol(key):
            return field[1]
    return None


def _findLibraryEntry(parsed_data, lib_name):
    # Library nicknames must be unique within a lib table
    for item in parsed_data:
        if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("lib"):
            if str(_getLibraryEntryValue(item, "name")) == str(lib_name):
                return item
    return None


def _isLibraryConfigured(parsed_data, lib_name, lib_path, table_name):
    entry = _findLibraryEntry(parsed_data, lib_name)
    if entry is None:
        return False

    existing_uri = _getLibraryEntryValue(entry, "uri")
    if str(existing_uri) != str(lib_path):
        print(f"Library '{lib_name}' already exists in {table_name} with a different URI ({existing_uri}), skipping")
    return True


def _isLibraryRow(item):
    return isinstance(item, list) and len(item) > 0 and item[0] == Symbol("lib")


def _createLibraryRow(lib_name, lib_type, lib_path, lib_options = "", lib_description = ""):
    return [
        Symbol("lib"),
        [Symbol("name"), lib_name],
        [Symbol("type"), lib_type],
        [Symbol("uri"), lib_path],
        [Symbol("options"), lib_options],
        [Symbol("descr"), lib_description]
    ]


def _setLibraryEntryValue(entry, key, value):
    for field in entry[1:]:
        if isinstance(field, list) and len(field) >= 2 and field[0] == Symbol(key):
            field[1] = value
            return


def _readLibTable(table_path, table_type):
    if not os.path.exists(table_path):
        return [Symbol(table_type), [Symbol("version"), LIB_TABLE_VERSION]]

    with open(table_path, 'r', encoding='utf-8') as f:
        return loads(f.read())


def _formatLibTable(parsed_data):
    # KiCad's table parser does not accept whitespace after an opening parenthesis of the table or a row,
    # so the table is written in KiCad's own layout instead of sexpdata's pretty print
    lines = ["(" + str(parsed_data[0])]
    for item in parsed_data[1:]:
        if _isLibraryRow(item):
            lines.append("\t(lib " + " ".join(dumps(field) for field in item[1:]) + ")")
        else:
            lines.append("\t" + dumps(item))
    lines.append(")")
    return "\n".join(lines) + "\n"


def _writeLibTable(table_path, parsed_data):
    with open(table_path, 'w', encoding='utf-8') as f:
        f.write(_formatLibTable(parsed_data))


def _addLibrary(table_path, table_type, lib_name, lib_type, lib_path, lib_options, lib_description):
    parsed_data = _readLibTable(table_path, table_type)

    if _isLibraryConfigured(parsed_data, lib_name, lib_path, table_path):
        return False

    parsed_data.append(_createLibraryRow(lib_name, lib_type, lib_path, lib_options, lib_description))
    _writeLibTable(table_path, parsed_data)
    return True


def _removeLibrary(table_path, table_type, lib_name, lib_type, lib_path):
    if not os.path.exists(table_path):
        return False

    parsed_data = _readLibTable(table_path, table_type)

    for i, item in enumerate(parsed_data):
        if _isLibraryRow(item) \
                and str(_getLibraryEntryValue(item, "name")) == str(lib_name) \
                and str(_getLibraryEntryValue(item, "type")) == str(lib_type) \
                and str(_getLibraryEntryValue(item, "uri")) == str(lib_path):
            del parsed_data[i]
            _writeLibTable(table_path, parsed_data)
            return True

    return False


# table_file defaults to KiCad's global table; KiPart libraries are stored in the library's own table
# (see GetLocalSymbolLibTableFile / GetLocalFootprintLibTableFile)

def addFootprintLibrary(lib_name, lib_type, lib_path, lib_options = "", lib_description = "", table_file = None):
    return _addLibrary(table_file or GetKiCadFootprintLibTableFile(), FP_LIB_TABLE_TYPE, lib_name, lib_type, lib_path, lib_options, lib_description)


def removeFootprintLibrary(lib_name, lib_type, lib_path, table_file = None):
    return _removeLibrary(table_file or GetKiCadFootprintLibTableFile(), FP_LIB_TABLE_TYPE, lib_name, lib_type, lib_path)


def addSymbolLibrary(lib_name, lib_type, lib_path, lib_options = "", lib_description = "", table_file = None):
    return _addLibrary(table_file or GetKiCadSymbolLibTableFile(), SYM_LIB_TABLE_TYPE, lib_name, lib_type, lib_path, lib_options, lib_description)


def removeSymbolLibrary(lib_name, lib_type, lib_path, table_file = None):
    return _removeLibrary(table_file or GetKiCadSymbolLibTableFile(), SYM_LIB_TABLE_TYPE, lib_name, lib_type, lib_path)



def _isKiPartUri(uri, lib_path_key):
    pattern = r"^\$\{" + re.escape(lib_path_key) + r"_(" + "|".join(KIPART_VAR_SUFFIXES) + r")\}"
    return re.match(pattern, str(uri)) is not None


def _getLibTablePairs(lib_base_path):
    # (global table, library table, table type)
    return [
        (GetKiCadSymbolLibTableFile(), GetLocalSymbolLibTableFile(lib_base_path), SYM_LIB_TABLE_TYPE),
        (GetKiCadFootprintLibTableFile(), GetLocalFootprintLibTableFile(lib_base_path), FP_LIB_TABLE_TYPE),
    ]


def registerLibraryTables(lib_name, lib_path_key, lib_base_path):
    """Create the library's own sym-lib-table / fp-lib-table and chain them into KiCad's global tables.

    Libraries that were added directly to the global tables by older versions are moved to the library's tables.
    """
    if not lib_base_path or not os.path.isdir(lib_base_path):
        return False

    for global_file, local_file, table_type in _getLibTablePairs(lib_base_path):
        global_table = _readLibTable(global_file, table_type)
        local_table = _readLibTable(local_file, table_type)
        global_changed = False

        for item in list(global_table):
            if _isLibraryRow(item) \
                    and str(_getLibraryEntryValue(item, "type")) != CHAINED_TABLE_TYPE \
                    and _isKiPartUri(_getLibraryEntryValue(item, "uri"), lib_path_key):
                global_table.remove(item)
                global_changed = True
                if _findLibraryEntry(local_table, _getLibraryEntryValue(item, "name")) is None:
                    local_table.append(item)
                print(f"Moved library '{_getLibraryEntryValue(item, 'name')}' from {global_file} to {local_file}")

        _writeLibTable(local_file, local_table)

        table_uri = "${" + lib_path_key + "_BASE_PATH}/" + os.path.basename(local_file)
        if not _isLibraryConfigured(global_table, lib_name, table_uri, global_file):
            global_table.append(_createLibraryRow(lib_name, CHAINED_TABLE_TYPE, table_uri, "", f"KiPart library {lib_name}"))
            global_changed = True

        if global_changed:
            _writeLibTable(global_file, global_table)

    return True


def unregisterLibraryTables(lib_path_key):
    """Remove the chained library tables (and any directly added libraries) of a KiPart library from KiCad's global tables."""
    for global_file, table_type in [(GetKiCadSymbolLibTableFile(), SYM_LIB_TABLE_TYPE), (GetKiCadFootprintLibTableFile(), FP_LIB_TABLE_TYPE)]:
        if not os.path.exists(global_file):
            continue

        global_table = _readLibTable(global_file, table_type)
        remaining = [item for item in global_table if not (_isLibraryRow(item) and _isKiPartUri(_getLibraryEntryValue(item, "uri"), lib_path_key))]
        if len(remaining) != len(global_table):
            _writeLibTable(global_file, remaining)


def updateLibraryTables(old_name, old_path_key, new_name, new_path_key, lib_base_path):
    """Apply a changed library name / path key to the library's own tables and its entries in KiCad's global tables."""
    unregisterLibraryTables(old_path_key)

    if lib_base_path and os.path.isdir(lib_base_path):
        for _, local_file, table_type in _getLibTablePairs(lib_base_path):
            if not os.path.exists(local_file):
                continue

            local_table = _readLibTable(local_file, table_type)
            for item in local_table:
                if not _isLibraryRow(item):
                    continue
                uri = str(_getLibraryEntryValue(item, "uri"))
                if _isKiPartUri(uri, old_path_key):
                    _setLibraryEntryValue(item, "uri", "${" + new_path_key + uri[len("${" + old_path_key):])
                if str(_getLibraryEntryValue(item, "type")) == "HTTP" and str(_getLibraryEntryValue(item, "name")) == str(old_name):
                    _setLibraryEntryValue(item, "name", new_name)
            _writeLibTable(local_file, local_table)

    return registerLibraryTables(new_name, new_path_key, lib_base_path)
