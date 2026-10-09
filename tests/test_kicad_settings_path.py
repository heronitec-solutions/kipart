import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from KiPartClient.KiCadSettings import _default_kicad_settings_dir, _getKiCadEnvVars


def test_linux_settings_dir_uses_xdg_config_home():
    path = _default_kicad_settings_dir(
        "10.0",
        platform="linux",
        environ={"XDG_CONFIG_HOME": os.path.join("/tmp", "cfg")},
        home=os.path.join("/home", "user"),
    )
    assert path == os.path.join("/tmp", "cfg", "kicad", "10.0")


def test_linux_settings_dir_defaults_to_home_config():
    path = _default_kicad_settings_dir(
        "10.0",
        platform="linux",
        environ={},
        home=os.path.join("/home", "user"),
    )
    assert path == os.path.join("/home", "user", ".config", "kicad", "10.0")
    assert "APPDATA" not in path
    assert "AppData" not in path


def test_macos_settings_dir():
    path = _default_kicad_settings_dir(
        "9.0",
        platform="darwin",
        environ={},
        home=os.path.join("/Users", "user"),
    )
    assert path == os.path.join("/Users", "user", "Library", "Preferences", "kicad", "9.0")


def test_windows_settings_dir_uses_appdata():
    appdata = os.path.join("C:\\Users", "user", "AppData", "Roaming")
    path = _default_kicad_settings_dir(
        "10.0",
        platform="win32",
        environ={"APPDATA": appdata},
        home=os.path.join("C:\\Users", "user"),
    )
    assert path == os.path.join(appdata, "kicad", "10.0")


def test_env_var_paths_join_subdirectories():
    base = os.path.join("library-root")
    variables = _getKiCadEnvVars("DEMO", base)
    assert variables["DEMO_BASE_PATH"] == base
    assert variables["DEMO_SYMBOL_DIR"] == os.path.join(base, "Symbols")
    assert variables["DEMO_FOOTPRINT_DIR"] == os.path.join(base, "Footprints")
    assert variables["DEMO_3DMODEL_DIR"] == os.path.join(base, "Packages3D")
    assert variables["DEMO_DATASHEET_DIR"] == os.path.join(base, "Datasheets")
    assert variables["DEMO_TEMPLATE_DIR"] == os.path.join(base, "Templates")
