import os
from pathlib import Path
from .sexpdata import loads, dumps, Symbol


SYMBOL_LIB_EXTENSION = ".kicad_symdir"
SYMBOL_FILE_EXTENSION = ".kicad_sym"
DEFAULT_SYMBOL_LIB_VERSION = 20220914
SYMBOL_LIB_GENERATOR = "kicad_symbol_editor"

# Matches KiCad's EscapeString(..., CTX_FILENAME) so KiCad and the sync use the same file per symbol,
# extended by '*' and '?' which are not allowed in Windows file names
_FILENAME_ESCAPES = {
    '/': '{slash}',
    '\\': '{backslash}',
    '"': '{dblquote}',
    '<': '{lt}',
    '>': '{gt}',
    '|': '{bar}',
    ':': '{colon}',
    '\t': '{tab}',
    '\n': '{return}',
    '\r': '{return}',
    '*': '{asterisk}',
    '?': '{question}',
}


def getSymbolFileName(symbol_name):
    return "".join(_FILENAME_ESCAPES.get(c, c) for c in str(symbol_name)) + SYMBOL_FILE_EXTENSION


def _isSymbolEntry(elem):
    return isinstance(elem, list) and len(elem) >= 2 and elem[0] == Symbol("symbol")


def _toVersion(version):
    try:
        return int(version)
    except (TypeError, ValueError):
        return DEFAULT_SYMBOL_LIB_VERSION


def getLibraryVersion(parsed_data):
    for elem in parsed_data:
        if isinstance(elem, list) and len(elem) >= 2 and elem[0] == Symbol("version"):
            return _toVersion(elem[1])
    return DEFAULT_SYMBOL_LIB_VERSION


def readSymbolFile(file):
    with open(file, 'r', encoding='utf-8') as f:
        return loads(f.read())


def writeSymbolFile(file, symbols, version = DEFAULT_SYMBOL_LIB_VERSION):
    parsed_data = [
        Symbol("kicad_symbol_lib"),
        [Symbol("version"), _toVersion(version)],
        [Symbol("generator"), SYMBOL_LIB_GENERATOR],
    ] + list(symbols)

    with open(file, 'w', encoding='utf-8') as f:
        f.write(dumps(parsed_data, pretty_print = "True"))


def _findSymbolInFile(file, symbol_name):
    parsed_data = readSymbolFile(file)
    for elem in parsed_data:
        if _isSymbolEntry(elem) and str(elem[1]) == str(symbol_name):
            return {'name': str(elem[1]), 'data': elem, 'file': Path(file), 'version': getLibraryVersion(parsed_data)}
    return None


def readSymbolLibrary(lib_path):
    """Return all symbols of an unpacked library. A file may contain more than one symbol."""
    entries = []
    if not os.path.isdir(lib_path):
        return entries

    for f in sorted(os.scandir(lib_path), key = lambda e: e.name):
        if not f.is_file() or not f.name.endswith(SYMBOL_FILE_EXTENSION):
            continue
        parsed_data = readSymbolFile(f.path)
        version = getLibraryVersion(parsed_data)
        for elem in parsed_data:
            if _isSymbolEntry(elem):
                entries.append({'name': str(elem[1]), 'data': elem, 'file': Path(f.path), 'version': version})

    return entries


def findSymbol(lib_path, symbol_name):
    expected_file = Path(lib_path) / getSymbolFileName(symbol_name)
    if expected_file.is_file():
        entry = _findSymbolInFile(expected_file, symbol_name)
        if entry is not None:
            return entry

    # file name does not follow the naming scheme (e.g. created outside of KiCad): search all files
    for entry in readSymbolLibrary(lib_path):
        if entry['name'] == str(symbol_name):
            return entry
    return None


def saveSymbol(lib_path, symbol_data, version = DEFAULT_SYMBOL_LIB_VERSION):
    """Create or replace a symbol in an unpacked library."""
    symbol_name = str(symbol_data[1])
    existing = findSymbol(lib_path, symbol_name)

    if existing is None:
        os.makedirs(lib_path, exist_ok = True)
        writeSymbolFile(Path(lib_path) / getSymbolFileName(symbol_name), [symbol_data], version)
        return

    parsed_data = readSymbolFile(existing['file'])
    for index, elem in enumerate(parsed_data):
        if _isSymbolEntry(elem) and str(elem[1]) == symbol_name:
            parsed_data[index] = symbol_data
            break

    with open(existing['file'], 'w', encoding='utf-8') as f:
        f.write(dumps(parsed_data, pretty_print = "True"))


def deleteSymbol(lib_path, symbol_name):
    existing = findSymbol(lib_path, symbol_name)
    if existing is None:
        return False

    parsed_data = readSymbolFile(existing['file'])
    parsed_data = [elem for elem in parsed_data if not (_isSymbolEntry(elem) and str(elem[1]) == str(symbol_name))]

    if any(_isSymbolEntry(elem) for elem in parsed_data):
        with open(existing['file'], 'w', encoding='utf-8') as f:
            f.write(dumps(parsed_data, pretty_print = "True"))
    else:
        os.remove(existing['file'])
    return True


def _getExtends(symbol_data):
    for elem in symbol_data:
        if isinstance(elem, list) and len(elem) >= 2 and elem[0] == Symbol("extends"):
            return str(elem[1])
    return None


def writePackedSymbol(lib_path, symbol_name, target_file):
    """Write a symbol together with all symbols it extends into a single packed library file.

    Derived symbols of an unpacked library cannot be loaded on their own (e.g. by kicad-cli).
    """
    entry = findSymbol(lib_path, symbol_name)
    if entry is None:
        return False

    symbols = [entry['data']]
    visited = {entry['name']}
    parent_name = _getExtends(entry['data'])
    while parent_name is not None and parent_name not in visited:
        parent = findSymbol(lib_path, parent_name)
        if parent is None:
            break
        symbols.insert(0, parent['data'])
        visited.add(parent_name)
        parent_name = _getExtends(parent['data'])

    writeSymbolFile(target_file, symbols, entry['version'])
    return True


def unpackSymbolLibrary(packed_file, lib_path):
    """Split a packed .kicad_sym library into an unpacked library directory and remove the packed file."""
    parsed_data = readSymbolFile(packed_file)
    version = getLibraryVersion(parsed_data)

    os.makedirs(lib_path, exist_ok = True)
    for elem in parsed_data:
        if _isSymbolEntry(elem):
            writeSymbolFile(Path(lib_path) / getSymbolFileName(elem[1]), [elem], version)

    os.remove(packed_file)
