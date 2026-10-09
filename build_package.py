import os
import shutil
import json
import zipfile
import hashlib
from pathlib import Path


BUILD_DIR = 'tmp'
OUTPUT_DIR = 'out'
PLUGIN_ZIP = 'kipart.zip'
SCRIPT_NAME = "build_package.py"


def recreate_out_dirs():
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
        print(f"Deleted existing '{BUILD_DIR}' directory.")
        
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
        print(f"Deleted existing '{OUTPUT_DIR}' directory.")

    os.makedirs(BUILD_DIR)
    os.makedirs(OUTPUT_DIR)
    print(f"Created new '{OUTPUT_DIR}' directory.")


def create_build_subdirs():
    # Create tmp/plugins and tmp/resources.
    plugins_dir = Path(BUILD_DIR) / "plugins"
    resources_dir = Path(BUILD_DIR) / "resources"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created build subdirectories: '{plugins_dir}' and '{resources_dir}'.")


def copy_python_files_to_plugins():
    # Copy all *.py files from script root into tmp/plugins, excluding build_package.py.
    root = Path(__file__).resolve().parent

    for py_file in root.glob("*.py"):
        if py_file.name == SCRIPT_NAME:
            continue
        shutil.copy2(py_file, Path(BUILD_DIR) / "plugins" / py_file.name)

    print(f"Copied Python files to '{Path(BUILD_DIR) / "plugins"}' (excluding '{SCRIPT_NAME}').")


def copy_plugin_assets():
    # Copy required non-py assets into the correct build locations.
    root = Path(__file__).resolve().parent

    # extpicknplace_24x24.png -> tmp/plugins
    shutil.copy2(root / "kipart_24x24.png", Path(BUILD_DIR) / "plugins" / "kipart_24x24.png")

    # metadata.json -> tmp
    shutil.copy2(root / "metadata.json", Path(BUILD_DIR) / "metadata.json")
    shutil.copy2(root / "metadata.json", Path(BUILD_DIR) / "plugins" / "metadata.json")

    # kipart_64x64.png -> tmp/resources/icon.png
    shutil.copy2(root / "kipart_64x64.png", Path(BUILD_DIR) / "resources" / "icon.png")

    print("Copied asset files (24x24 icon, metadata.json, 64x64 icon -> resources/icon.png).")


def get_dir_size_bytes(dir_path: Path) -> int:
    total = 0
    for p in dir_path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def write_metadata_sizes(install_size: int, download_size: int) -> None:
    metadata_path = Path(BUILD_DIR) / "metadata.json"
    with metadata_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    versions = data.get("versions", [])
    if not versions or not isinstance(versions, list):
        raise ValueError("metadata.json does not contain a non-empty 'versions' list.")

    # Update FIRST entry (typical for single-version packages)
    versions[0]["install_size"] = int(install_size)
    versions[0]["download_size"] = int(download_size)

    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")  # keep file newline-friendly
        
    shutil.copy2(Path(BUILD_DIR) / "metadata.json", Path(BUILD_DIR) / "plugins" / "metadata.json")
    shutil.copy2(Path(BUILD_DIR) / "metadata.json", "./metadata.json")

    print(
        f"Updated metadata.json: install_size={install_size} bytes, download_size={download_size} bytes."
    )
    
    
def build_zip_and_update_metadata():
    build_root = Path(BUILD_DIR)
    out_zip = Path(OUTPUT_DIR) / PLUGIN_ZIP

    install_size = get_dir_size_bytes(build_root)

    # We want metadata.download_size to match the FINAL zip size.
    # Because updating metadata changes the zip content (and thus its size),
    # we iterate a couple of times until it stabilizes.
    download_size = 0
    last_zip_size = None

    for i in range(1, 4):  # small bounded loop (usually stabilizes in 2 passes)
        write_metadata_sizes(install_size=install_size, download_size=download_size)
        zip_size = create_zip_from_build_dir(out_zip)

        if last_zip_size is not None and zip_size == last_zip_size and download_size == zip_size:
            print("Zip size stabilized and metadata matches final archive size.")
            return

        last_zip_size = zip_size
        download_size = zip_size

        # Requirement: delete zip archive and create it again
        # (we do it by looping; next iteration deletes and rebuilds)

    # Ensure metadata matches the last archive size, then recreate once more to embed it.
    write_metadata_sizes(install_size=install_size, download_size=download_size)
    if out_zip.exists():
        out_zip.unlink()
    create_zip_from_build_dir(out_zip)
    print("Final zip rebuilt with updated metadata embedded.")
    
    
def create_zip_from_build_dir(zip_path: Path) -> int:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    build_root = Path(BUILD_DIR)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in build_root.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(build_root)  # content at zip root
                zf.write(file_path, arcname)

    size = zip_path.stat().st_size
    print(f"Created zip: '{zip_path}' ({size} bytes).")
    return size


def calculate_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


if __name__ == "__main__":
    recreate_out_dirs()
    create_build_subdirs()
    copy_python_files_to_plugins()
    copy_plugin_assets()

    build_zip_and_update_metadata()
    
    sha256 = calculate_sha256(Path(OUTPUT_DIR) / PLUGIN_ZIP)
    print(f"SHA-256: {sha256}")
    
    # delete temporary build dir
    shutil.rmtree(BUILD_DIR)
    print(f"Build completed successfully. Output: '{Path(OUTPUT_DIR) / PLUGIN_ZIP}'.")