import os
import shutil
from pathlib import Path
from .Misc import ReturnCode
from .KiCadSettings import addSymbolLibrary, registerLibraryTables, GetLocalSymbolLibTableFile
from .RestAPI import RestAPI
from .MetaFile import emptyMeta, save as saveMeta
import json


######################################################################################

def checkIfLibraryPathExists(config):
    
    if not config['output_path'].startswith('/') and not (config['output_path'][1] == ":"):
        config['output_path'] = os.path.dirname(__file__) + '/' + config['output_path']

    # check if sync meta file exists (if not => download everything new)
    meta_file = config['output_path'] + '/.kipart_sync'
    meta_file = Path(meta_file)
    return meta_file.exists() and meta_file.is_file()


def createLibraryFiles(config):
    
    if not config['output_path'].startswith('/') and not (config['output_path'][1] == ":"):
        config['output_path'] = os.path.dirname(__file__) + '/' + config['output_path']

    try:    
        # create output directory
        isExist = os.path.exists(config['output_path'] )
        if isExist:
            shutil.rmtree(config['output_path'] )
            print("Output dir deleted: " + config['output_path'] )
    
        os.makedirs(config['output_path'] )
        os.makedirs(config['output_path']  + '/Footprints')
        os.makedirs(config['output_path']  + '/Symbols')
        os.makedirs(config['output_path']  + '/Packages3D')
        os.makedirs(config['output_path']  + '/Datasheets')
        os.makedirs(config['output_path']  + '/Templates')
        print("Output dirs created")
    except Exception:
        return ReturnCode.FileWriteError

    # Meta v2 with last_commit_id from /api/info
    last_commit_id = None
    try:
        api = RestAPI(config, "")
        info = api.info()
        last_commit_id = (info or {}).get('headCommitId')
    except Exception as e:
        print("Warning: could not fetch /api/info for last_commit_id:", e)

    meta_json_object = emptyMeta(last_commit_id=last_commit_id)
    
    # Create library file json object
    json_object = {
        "meta" : {
            "version": 1.0
        },
        "name": "KiPart HTTP Library",
        "description": "A KiCad library sourced from a REST API",
        "source": {
            "type": "REST_API",
            "api_version": "v1",
            "root_url": config['api_url'],
            "token": config.get('api_user_token') or '',
            "timeout_parts_seconds": 60,
            "timeout_categories_seconds": 600
        }
    }
    

    # Write meta file (v2)
    try:
        saveMeta(config['output_path'], meta_json_object)
    except Exception:
        return ReturnCode.FileWriteError
    
    # create database library file
    print('Creating KiCAD http library file: ' + config['output_path'] + '/HttpLibrary.kicad_httplib')  
    dblFile = open(config['output_path'] + '/HttpLibrary.kicad_httplib', 'x')
    json_data = json.dumps(json_object, indent = 4)
    dblFile.write(json_data)
    dblFile.close()
    
    # Add symbol HTTP library to the library's own table and chain the tables into KiCad's global tables
    try:
        addSymbolLibrary(config['name'], "HTTP", "${" + config['path_key'] + "_BASE_PATH}/HttpLibrary.kicad_httplib", table_file = GetLocalSymbolLibTableFile(config['output_path']))
        registerLibraryTables(config['name'], config['path_key'], config['output_path'])
    except Exception as e:
        print("Warning: could not register KiCad library tables (ok outside KiCad):", e)

    return ReturnCode.OK


def refreshHttpLibraryFile(config):
    """KiCad only accepts api_version \"v1\". Update an existing library file in place."""
    path = Path(config['output_path']) / 'HttpLibrary.kicad_httplib'
    if not path.is_file():
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return
    source = data.setdefault('source', {})
    source['type'] = 'REST_API'
    source['api_version'] = 'v1'
    if config.get('api_url'):
        source['root_url'] = config['api_url']
    source['token'] = config.get('api_user_token') or ''
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
        f.write('\n')
