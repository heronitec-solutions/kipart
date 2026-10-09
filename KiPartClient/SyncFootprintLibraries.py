import os
import json
from pathlib import Path
from .Misc import ActionType, ReturnCode
from .ChangeReview import resolve_action
from .RestAPI import RestAPI
from .KiCadSettings import addFootprintLibrary, removeFootprintLibrary, GetLocalFootprintLibTableFile
from collections import Counter
import datetime


class SyncFootprintLibraries:
    def __init__(self, config):
        self._config = config
        self._directory = "Footprints"
        self._api_name = "libraryfile"
        self._meta_key = "footprints"

        self._api = RestAPI(self._config, self._api_name)


    def check(self, force_remote=False):
        print('Checking footprint libraries ...')

        if not self._config['output_path'].startswith('/') and not (self._config['output_path'][1] == ":"):
            self._config['output_path'] = os.path.dirname(__file__) + '/' + self._config['output_path']

        from .MetaFile import ensureV2
        meta = ensureV2(self._config['output_path'], self._api, self._config)
        meta_data = dict(meta.get(self._meta_key) or {})

        read_path = self._config['output_path']  + '/' + self._directory
        if not os.path.exists(read_path):
            os.makedirs(self._config['output_path']  + '/' + self._directory)

        # find local libraries
        lib_dirs = [f.name.replace('.pretty', '') for f in os.scandir(read_path) if f.is_dir() and f.name.endswith('.pretty')]

        num_all = len(lib_dirs)

        # get all entries in database
        lib_files = self._api.getFilteredList('type', '0')

        sync_actions = []
        remaining_meta_libs = set(meta_data.keys())

        for lib_file in lib_files:
            in_meta = lib_file['filename'] in meta_data
            dir_index = -1
            for d_index, lib_dir in enumerate(lib_dirs):
                if lib_file['filename'] == lib_dir:
                    dir_index = d_index
                    break

            if not in_meta and dir_index < 0:
                sync_actions.append({"type": ActionType.Download, "library": lib_file['filename'], "id": lib_file['id']})
            elif in_meta and dir_index < 0:
                if force_remote:
                    sync_actions.append({"type": ActionType.Download, "library": lib_file['filename'], "id": lib_file['id']})
                else:
                    sync_actions.append({"type": ActionType.DeleteRemote, "library": lib_file['filename'], "id": lib_file['id']})
                remaining_meta_libs.discard(lib_file['filename'])
            elif not in_meta and dir_index >= 0:
                sync_actions.append({"type": ActionType.Conflict, "library": lib_file['filename'], "id": lib_file['id'], 'comment': 'Local and remote version of library are new'})
                lib_dirs.pop(dir_index)
            else:
                remaining_meta_libs.discard(lib_file['filename'])
                lib_dirs.pop(dir_index)

        for lib_dir in lib_dirs:
            if lib_dir in remaining_meta_libs:
                sync_actions.append({"type": ActionType.DeleteLocal, "library": lib_dir})
                remaining_meta_libs.discard(lib_dir)
            else:
                sync_actions.append({"type": ActionType.Upload, "library": lib_dir})

        for key in remaining_meta_libs:
            sync_actions.append({"type": ActionType.DeleteLocal, "library": key})

        
        # count jobs
        action_counts = Counter(sync_action['type'] for sync_action in sync_actions)

        # output result of check
        print("Footprint libraries analyzed:")
        print("Download:", str(action_counts[ActionType.Download]))
        print("Upload:", str(action_counts[ActionType.Upload]))
        print("Delete:", str(action_counts[ActionType.DeleteRemote] + action_counts[ActionType.DeleteLocal]))
        if action_counts[ActionType.Conflict] > 0:
            print('Conflict: ' + str(action_counts[ActionType.Conflict]), )
            for sync_action in sync_actions:
                if sync_action['type'] == ActionType.Conflict:
                    print('   ', sync_action.get('library') or sync_action.get('file'), ':', sync_action['comment'])
        else:
            print("Conflict:", str(action_counts[ActionType.Conflict]))

        sync_data = {}
        sync_data["cntNew"] = action_counts[ActionType.Download] + action_counts[ActionType.Upload]
        sync_data["cntChanged"] = action_counts[ActionType.UpdateRemote] + action_counts[ActionType.UpdateLocal]
        sync_data["cntDeleted"] = action_counts[ActionType.DeleteRemote] + action_counts[ActionType.DeleteLocal]
        sync_data["cntConflict"] = action_counts[ActionType.Conflict]
        sync_data["cntUnchanged"] = num_all + action_counts[ActionType.Download] - len(sync_actions)
        if sync_data["cntUnchanged"] < 0:
            sync_data["cntUnchanged"] = 0
        sync_data["sync_actions"] = sync_actions
        return sync_data
    
    
    def sync(self, sync_actions, sub_progress_callback):
        print('Syncing footprint libraries ...')

        if not self._config['output_path'].startswith('/') and not (self._config['output_path'][1] == ":"):
            self._config['output_path'] = os.path.dirname(__file__) + '/' + self._config['output_path']

        read_path = self._config['output_path']  + '/' + self._directory
        if not os.path.exists(read_path):
            os.makedirs(self._config['output_path']  + '/' + self._directory)

        if len(sync_actions) > 0:
            sub_progress_callback(True, False, "", len(sync_actions))

        prog_cnt = 0

        resolved_actions = []
        for sync_action in sync_actions:
            prog_txt = ""
            resolved = resolve_action(sync_action)
            if resolved is None:
                prog_txt = "ignored"
            else:
                resolved_actions.append(resolved)
                if resolved['type'] == ActionType.Upload:
                    self.__uploadFootprintLibrary(resolved['library'])
                    prog_txt = "uploaded"
                elif resolved['type'] == ActionType.Download:
                    self.__downloadFootprintLibrary(resolved['library'])
                    prog_txt = "downloaded"
                elif resolved['type'] == ActionType.DeleteLocal:
                    self.__deleteFootprintLibrary(resolved['library'])
                    prog_txt = "deleted"
                elif resolved['type'] == ActionType.DeleteRemote:
                    self.__deleteFootprintLibrary(resolved['library'], resolved.get('id'))
                    prog_txt = "deleted"

            prog_cnt += 1
            sub_progress_callback(False, False, sync_action['library'] + " " + prog_txt, prog_cnt)

        # update meta file list
        f = open(self._config['output_path'] + '/.kipart_sync')
        meta_data = json.load(f)
        f.close()

        # updated sync actions to meta file (except conflicts) — v2 dict form
        if not isinstance(meta_data.get('footprints'), dict):
            meta_data['footprints'] = {}
        for sync_action in resolved_actions:
            if sync_action['type'] == ActionType.Upload or sync_action['type'] == ActionType.Download:
                meta_data['footprints'].setdefault(sync_action['library'], {})
            elif sync_action['type'] == ActionType.DeleteLocal or sync_action['type'] == ActionType.DeleteRemote:
                meta_data['footprints'].pop(sync_action['library'], None)

        # updated timestamp
        meta_data["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f %z')

        # Write updated meta file
        metaFile = open(self._config['output_path'] + '/.kipart_sync', 'w')
        json_data = json.dumps(meta_data, indent = 4)
        metaFile.write(json_data)
        metaFile.close()

        if len(sync_actions) > 0:
            sub_progress_callback(False, True, "", 0)

        print("Footprint libraries synchronized")
    

    def __uploadFootprintLibrary(self, library):
        print('Create remote footprint library: ' + library)

        # create json object
        json_data = {
            "type": 0,
            "name": library,
            "filename": library,
            "version": "20221018"
        }

        # upload data
        try:
            return self._api.add(json_data)
        except:
            return ReturnCode.NoConnection


    def __downloadFootprintLibrary(self, library):
        # download library file
        print('Create local footprint library: ' + library)  

        # add to kicad settings
        addFootprintLibrary(str(library), "KiCad", "${" + self._config['path_key'] + "_FOOTPRINT_DIR}/" + str(library) + ".pretty", table_file = GetLocalFootprintLibTableFile(self._config['output_path']))

        # create directory
        try:
            os.makedirs(self._config['output_path'] + '/' + self._directory + '/' + library + '.pretty', exist_ok=True) 
            return ReturnCode.OK
        except:
            return ReturnCode.FileWriteError
        
    
    def __deleteFootprintLibrary(self, library, id = None):
        print('Delete footprint library: ' + library)

        local_path = Path(self._config['output_path'] + '/' + self._directory + '/' + library + '.pretty')

        # delete local directory
        try:
            if os.path.exists(local_path):
                os.rmdir(local_path)
        except:
            return ReturnCode.FileWriteError

        # add to kicad settings
        removeFootprintLibrary(str(library), "KiCad", "${" + self._config['path_key'] + "_FOOTPRINT_DIR}/" + str(library) + ".pretty", table_file = GetLocalFootprintLibTableFile(self._config['output_path']))

        # delete remote entry
        if(id != None):
            try:
                self._api.delete(id)
            except:
                return ReturnCode.NoConnection
        
        return ReturnCode.OK
