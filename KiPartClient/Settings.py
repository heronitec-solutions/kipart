import json
from pathlib import Path

class Settings:

    # Define the target directory and file name
    _target_dir = Path.home() / ".kipart"
    _target_file_name = "config.json"
    _target_file_path = _target_dir / _target_file_name
    _config_version = 0
    _current_index = -1


    def __init__(self, parent):
        self.parent = parent
        self._db_library_list = self.load_config_json()

        if self._db_library_list is None:
            self._db_library_list = []
            self.store_config_json()

        dirty = False
        for lib in self._db_library_list:
            if 'author' in lib:
                lib.pop('author', None)
                dirty = True
        if dirty:
            self.store_config_json()


    def load_config_json(self):

        self._current_index = -1

        # Check if the target file exists
        if self._target_file_path.is_file():
            # Open and parse the JSON file
            try:
                with open(self._target_file_path, 'r') as file:
                    config_data = json.load(file)            
                    self._config_version = config_data['meta']['version']         
                    return config_data['libraries']
            except json.JSONDecodeError as e:
                print(f"Config file '{self._target_file_name}' could not be parsed: {e}")
                return None
        else:
            print(f"Config file does not exist.")
            return None


    def store_config_json(self):

        # Create json object
        config_data = {
            "meta": {
                "version": 0
            },
            "libraries": []
        }

        # add libraries to the json object
        if len(self._db_library_list) > 0:
            for library in self._db_library_list:
                # add libraries to the json object
                config_data["libraries"].append(library)

        # Ensure the target directory exists
        self._target_dir.mkdir(parents=True, exist_ok=True)

        # Write the JSON data to the target file
        try:
            with open(self._target_file_path, 'w') as file:
                json.dump(config_data, file, indent=4)
        except Exception as e:
            print(f"Error writing JSON file: {e}")
            

    def get_library_list(self):
        if hasattr(self, "_db_library_list"):
            return self._db_library_list
        else:
            return []
    
    def set_current_index(self, index):
        self._current_index = index

    def get_current_library_data(self):
        if self._current_index >= 0 and self._current_index < len(self._db_library_list):
            return self._db_library_list[self._current_index]
        else:
            return None   

    def set_current_library_data(self, library_data):
        if self._current_index >= 0 and self._current_index < len(self._db_library_list):
            self._db_library_list[self._current_index] = library_data        
            self.store_config_json()
            #self.parent.emitUpdateLibraryList(self._current_index)

    def add_library_data(self, library_data):
        self._db_library_list.append(library_data)
        self.store_config_json()
        #self.parent.emitUpdateLibraryList(len(self._db_library_list) - 1)

    def remove_current_library(self):
        if self._current_index >= 0 and self._current_index < len(self._db_library_list):
            del self._db_library_list[self._current_index]
            self.store_config_json()
            self._current_index = self._current_index - 1
            #self.parent.emitUpdateLibraryList(self._current_index)