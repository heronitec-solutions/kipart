# KiPart  

This [KiCad EDA](https://www.kicad.org/) plugin utilizes the new KiCad database and http library feature and extends it with a web component to manage part data like part numbers, manufacturers, distributor order numbers...

## Web Component 

To use this plugin you need the KiPart web component. It can be found on [Docker Hub]() and [GitLab]().

## Server requirement (API v2)

**KiPart Client 2.0.0+ requires a KiPart Server with API version ≥ 2** (versioning, blob store, atomic commits). The plugin checks `GET /api/info` and refuses sync if `apiVersion < 2`.

### Author setting

Each library configuration has an **Author** field (default: Windows/login username). It is sent with every commit created during Sync.

### Commit dialog

When Sync has remote changes to upload, a commit dialog asks for a **required message** (and shows the change list). Cancel skips the upload; local downloads/renames/deletes are still applied.

### Meta file migration

`.kipart_sync` is now **v2** (UUID-keyed entries, `last_commit_id`). On first Check after upgrade, v1 meta is migrated automatically and backed up as `.kipart_sync.v1.bak`.

Blobs created by the server’s v1→v2 migration may still contain the old (non-canonical) text. After meta migration, Check detects semantic matches (local canonical text == canonicalize(server data)) and queues a one-time **canonicalisation commit** (`"Canonicalize library content after migration to API v2"`). The next Sync applies that commit automatically (no commit dialog for that commit only). Afterward, Check reports 0 changes.

### Multiple 3D models

Footprints may reference **several** `(model …)` blocks. Check/Sync uploads all of them with offset/scale/rotate/hide, and downloads restore models from the server `models[]` list.
## Installation

### Automated, via KiCad plugin manager

The KiPart plugin is part of the official KiCad repository. You can install it via the Plugin an Content Manager in KiCad.

### Manual, most current version

To get the most current version of the plugin, clone the repo in the plugin directory of your KiCad installtion:

```bash
# Linux (KiCad from Ubuntu PPA)
# TODO
# Linux (KiCad 9 from FlatPak)
cd <HOME>/.var/app/org.kicad.KiCad/data/kicad/9.0/3rdparty/plugins
# Windows
cd C:\Users\<USERNAME>\Documents\KiCad\9.0\3rdparty\plugins
# Mac
cd <HOME>/Documents/KiCad/9.0/3rdparty/plugins

# then clone the repo main branch
git clone --depth 1 https://github.com/heronitec-solutions/kipart
```

Restart KiCad and it should be visiable.

## Manual, latest stable release

Same as above, but instead cloning the main branch, clone the realease branch:

```bash
# clone the repo tag
git clone --depth 1 --branch release https://github.com/heronitec-solutions/kipart
```

### Manual, older version

Same as above, but instead cloning the main branch, clone the desired tag:

```bash
# clone the repo tag
git clone --depth 1 --branch v1.6.0 https://github.com/heronitec-solutions/kipart
```

## Known Problems

### Plugin icon position

At the moment (KiCad v9.0) it's only possible to display a plugin icon in the PCB editor. We will move it to the symbol and footprint editor when the required KiCad feature is available ([KiCad Issue 19418](https://gitlab.com/kicad/code/kicad/-/issues/19418))

### Missing Paths / Libraries

KiPart tries to add the required KiCad environment paths and libraries automatically. Because there is no cli method for that yet, KiPart modifies the setting files manually. This sometimes fails when KiCad does work with the files at the same time. If you are missing paths or libraries, you can crate it manually.

#### Adding Paths manually

For each Library it should create the following paths:

*{lib_path_key}*_BASE_PATH
*{lib_path_key}*_3DMODEL_DIR
*{lib_path_key}*_DATASHEET_DIR
*{lib_path_key}*_FOOTPRINT_DIR
*{lib_path_key}*_SYMBOL_DIR
*{lib_path_key}*_TEMPLATE_DIR

(Replace *{lib_path_key}* with your selected Path Key fot the library)

#### Adding HTTP Library manually

After that the HTTP-Library can be added (as a symbol library):

**Nickname:** *{lib_path_name}*
**Library Path:** ${*{lib_path_key}*_BASE_PATH}/HttpLibrary.kicad_httplib
**Library Fomat:** HTTP