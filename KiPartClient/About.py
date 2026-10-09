import json
from pathlib import Path


LICENSE_PARAGRAPHS = (
    "KiPart Client syncs parts, symbols, footprints and datasheets with a KiCad library.",
    "Copyright (C) 2026 Heronitec Solutions GmbH",
    (
        "This program is free software: you can redistribute it and/or modify "
        "it under the terms of the GNU General Public License as published by "
        "the Free Software Foundation, either version 3 of the License, or "
        "(at your option) any later version."
    ),
    (
        "This program is distributed in the hope that it will be useful, "
        "but WITHOUT ANY WARRANTY; without even the implied warranty of "
        "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the "
        "GNU General Public License for more details."
    ),
    (
        "You should have received a copy of the GNU General Public License "
        "along with this program. If not, see"
    ),
)

GPL_URL = "https://www.gnu.org/licenses/"

CONTACT = (
    ("Heronitec Solutions GmbH", None),
    ("Kreuzdelle 18", None),
    ("63872 Heimbuchenthal", None),
    ("Germany", None),
    ("info@heronitec-solutions.de", "mailto:info@heronitec-solutions.de"),
    ("https://github.com/heronitec-solutions/kipart", "https://github.com/heronitec-solutions/kipart"),
)

SERVER_LABELS = ("Server", "HTTP library", "Sync API", "Database schema")


def client_version():
    try:
        meta_path = Path(__file__).resolve().parent.parent / "metadata.json"
        with open(meta_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data["versions"][0]["version"]
    except Exception:
        return ""


def _show(value):
    if value is None or value == "":
        return "—"
    return str(value)


def version_fields(client, kicad, info):
    """Local client versions, plus the server fields reported by /api/info."""
    remote = info or {}
    return (
        ("Client", _show(client)),
        ("KiCad", _show(kicad)),
        ("Server", _show(remote.get("version"))),
        ("HTTP library", _show(remote.get("httpLibraryVersion"))),
        ("Sync API", _show(remote.get("apiVersion"))),
        ("Database schema", _show(remote.get("schemaVersion"))),
    )
