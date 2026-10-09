"""Canonical text form and hashing for KiCad symbols/footprints (API v2)."""

import hashlib
import re
from .sexpdata import loads, dumps, Symbol
from .Misc import getSymbolValue


PLACEHOLDER = "${PLACEHOLDER}"


def ensureTrailingNewline(text):
    if not text.endswith('\n'):
        text = text + '\n'
    # Exactly one trailing newline
    while text.endswith('\n\n'):
        text = text[:-1]
    return text


def _normalizeNewlines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def canonicalSymbolText(symbol_sexp):
    """Canonical form of a single (symbol ...) S-expression block."""
    text = dumps(symbol_sexp, pretty_print=True)
    text = _normalizeNewlines(text)
    return ensureTrailingNewline(text)


def stripPathVariable(path):
    """Remove ${VAR}/ or ${VAR}\\ prefix; normalise separators to /."""
    if path is None:
        return ''
    path = str(path).replace('\\', '/')
    path = re.sub(r'^\$\{[^}]+\}/+', '', path)
    return path.lstrip('/')


def splitModelPath(path):
    """Return (directory, filename) from a model path (after stripping ${...})."""
    cleaned = stripPathVariable(path)
    if not cleaned:
        return '', ''
    if '/' in cleaned:
        directory, filename = cleaned.rsplit('/', 1)
        directory = directory.strip('/')
        return directory, filename
    return '', cleaned


def normalizeModelPathForCanonical(path):
    """Normalise a model path to ${PLACEHOLDER}/<dir>/<file> or ${PLACEHOLDER}/<file>."""
    directory, filename = splitModelPath(path)
    if not filename:
        return PLACEHOLDER + '/'
    if directory:
        return f"{PLACEHOLDER}/{directory}/{filename}"
    return f"{PLACEHOLDER}/{filename}"


def _setModelPathString(model_block, new_path):
    """Set the path string of a (model ...) block (2nd element)."""
    if isinstance(model_block, list) and len(model_block) >= 2:
        model_block[1] = new_path
    return model_block


def canonicalFootprintText(parsed):
    """
    Canonical footprint text: pretty-printed S-expression with every
    (model \"...\") path normalised to ${PLACEHOLDER}/...
    """
    # Work on a deep-ish copy via re-parse so we don't mutate caller's tree
    text0 = dumps(parsed, pretty_print=True)
    parsed2 = loads(text0)

    for model in getSymbolValue(parsed2, 'model'):
        if isinstance(model, list) and len(model) >= 2 and isinstance(model[1], str):
            _setModelPathString(model, normalizeModelPathForCanonical(model[1]))

    text = dumps(parsed2, pretty_print=True)
    text = _normalizeNewlines(text)
    return ensureTrailingNewline(text)


def sha256Text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sha256Bytes(data):
    return hashlib.sha256(data).hexdigest()


def _xyzFromList(block, default):
    """Extract [x,y,z] from (offset|scale|rotate (xyz x y z))."""
    if not block or not isinstance(block, list):
        return list(default)
    for elem in block:
        if isinstance(elem, list) and len(elem) >= 4 and elem[0] == Symbol('xyz'):
            try:
                return [float(elem[1]), float(elem[2]), float(elem[3])]
            except (TypeError, ValueError):
                return list(default)
    return list(default)


def extractModels(parsed):
    """
    Read ALL (model ...) blocks with offset/scale/rotate/opacity/hide.
    Returns list of dict(position, directory, filename, offset, scale, rotate, opacity, hide).
    """
    models = []
    for position, model in enumerate(getSymbolValue(parsed, 'model')):
        if not isinstance(model, list) or len(model) < 2:
            continue
        path = model[1] if isinstance(model[1], str) else ''
        directory, filename = splitModelPath(path)

        offset = [0.0, 0.0, 0.0]
        scale = [1.0, 1.0, 1.0]
        rotate = [0.0, 0.0, 0.0]
        opacity = None
        hide = False

        for elem in model[2:]:
            if not isinstance(elem, list) or not elem:
                if elem == Symbol('hide') or elem == 'hide':
                    hide = True
                continue
            head = elem[0]
            if head == Symbol('offset'):
                offset = _xyzFromList(elem, offset)
            elif head == Symbol('scale'):
                scale = _xyzFromList(elem, scale)
            elif head == Symbol('rotate'):
                rotate = _xyzFromList(elem, rotate)
            elif head == Symbol('opacity') and len(elem) > 1:
                try:
                    opacity = float(elem[1])
                except (TypeError, ValueError):
                    opacity = None
            elif head == Symbol('hide'):
                hide = True

        # bare hide symbol as sibling
        for elem in model[2:]:
            if elem == Symbol('hide'):
                hide = True

        models.append({
            'position': position,
            'directory': directory,
            'filename': filename,
            'offset': offset,
            'scale': scale,
            'rotate': rotate,
            'opacity': opacity,
            'hide': hide,
        })
    return models


def setModelPaths(parsed, paths_by_position):
    """
    Write model path strings per position. paths_by_position: dict[int,str] or list.
    Models without a mapping are left unchanged.
    """
    if isinstance(paths_by_position, list):
        paths_by_position = {i: p for i, p in enumerate(paths_by_position)}

    models = getSymbolValue(parsed, 'model')
    for position, model in enumerate(models):
        if position in paths_by_position and isinstance(model, list) and len(model) >= 2:
            model[1] = paths_by_position[position]
    return parsed


def filePathKey(directory, filename):
    """Stable meta path key: dir/file without trailing slash on dir."""
    directory = (directory or '').replace('\\', '/').strip('/')
    filename = (filename or '').lstrip('/')
    if directory:
        return f"{directory}/{filename}"
    return filename
