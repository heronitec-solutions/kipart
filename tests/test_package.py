from build_package import copy_python_files_to_plugins


def test_pcm_package_contains_client_and_dialog_icons(tmp_path):
    copy_python_files_to_plugins(tmp_path)
    plugins = tmp_path / "plugins"

    assert (plugins / "__init__.py").is_file()
    assert (plugins / "kipart_action.py").is_file()
    assert (plugins / "KiPartClient" / "__init__.py").is_file()
    assert (plugins / "KiPartClient" / "LibrarySync.py").is_file()
    assert (plugins / "resources" / "icon_add.png").is_file()
    assert (plugins / "resources" / "icon_sync.png").is_file()
    assert not (plugins / "build_package.py").exists()
    assert not (plugins / "KiPartClient" / "__pycache__").exists()
