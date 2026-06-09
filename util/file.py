"""
version: 3.0.0
author: Wuyilingwei
This module provides CSV file management
This module is used to read and write CSV/TOML files
For v3: Focus on data update with change detection, no translation
Target utils version:
None (standalone)
"""
import os
import csv
import toml
import logging
import re
from collections import OrderedDict


def reorder_entry_fields(entry: OrderedDict) -> OrderedDict:
    """
    Reorder fields in entry to: raw, new, status, then language codes
    """
    if not isinstance(entry, dict):
        return entry
    
    ordered = OrderedDict()
    
    # Priority order: raw, new, status
    for field in ['raw', 'new', 'status']:
        if field in entry:
            ordered[field] = entry[field]
    
    # Then all other fields (language codes and others)
    for field, value in entry.items():
        if field not in ['raw', 'new', 'status']:
            ordered[field] = value
    
    return ordered



class CSV_File:
    """
    CSV file reader and TOML data updater for v3
    Handles data comparison and change detection
    No translation - only data preparation for cloud workflow
    """

    def __init__(self, id: int, name: str, raw: str) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.id = id
        self.name = name
        self.old_data = {}
        self.data = OrderedDict()
        self.new_raw_data = {}
        self.load_raw(raw)

    def is_valid_key(self, key: str) -> bool:
        """Validate if key contains only legal characters: A-Z, a-z, 0-9, _ and ."""
        if not key or not isinstance(key, str):
            return False
        # Allow A-Z, a-z, 0-9, underscore and . characters
        # Underscore and digits are used in real Timberborn keys, e.g. LV.MT.State_Open,
        # Building.NaturalOverhang1.Description, Knatte.Pillar_1.DisplayName
        return bool(re.match(r'^[A-Za-z0-9._]+$', key))

    def load_raw(self, path: str) -> None:
        """Load raw CSV file from mod"""
        if path is None:
            self.logger.error("Cannot load raw data: path is None")
            return
        try:
            with open(path, 'r', encoding='utf-8') as file:
                first_line = file.readline()
                if first_line.startswith('\ufeff'):
                    first_line = first_line.lstrip('\ufeff')  # Remove BOM
                reader = csv.reader([first_line] + file.readlines())
                for row in reader:
                    if not row:
                        continue
                    key = row[0]
                    # Skip header and comment rows
                    if key in ['id', 'ID']:
                        continue
                    # Skip comment rows based on the Comment column
                    if len(row) > 2 and row[2].strip().lower() == 'comment':
                        continue
                    # Skip keys containing '//' as they are used as separators
                    # Note: This checks for '//' anywhere in the key string
                    if '//' in key:
                        self.logger.debug(f"Skipping key '{key}' containing '//' (separator)")
                        continue
                    # Skip keys with invalid characters (only allow A-Z, a-z, and .)
                    if not self.is_valid_key(key):
                        self.logger.debug(f"Skipping key '{key}' with invalid characters (only A-Z, a-z, . allowed)")
                        continue
                    if len(row) > 1:
                        values = row[1:]
                        self.new_raw_data[key] = values[0] if values[0] else ""
            self.logger.info(f"Loaded {len(self.new_raw_data)} entries from {path}")
        except FileNotFoundError:
            self.logger.error(f"File not found: {path}")
        except Exception as e:
            self.logger.error(f"Error loading data from {path}: {e}")

    def load_old_data(self, path: str) -> None:
        """Load existing TOML file if it exists"""
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as file:
                    self.old_data = toml.load(file, _dict=OrderedDict)
                self.logger.info(f"Loaded old data from {path}")
            else:
                self.logger.info(f"No existing data file found: {path}")
                self.old_data = OrderedDict()
        except Exception as e:
            self.logger.error(f"Error loading old data from {path}: {e}")
            self.old_data = OrderedDict()

    def save_data(self, path: str, filename: str) -> None:
        """Save updated data to TOML file"""
        file_path = None
        try:
            if not os.path.exists(path):
                os.makedirs(path)
            file_path = os.path.join(path, f"{filename}.toml")

            # Validate data before dump: ensure all values are TOML-compatible
            # Convert any non-dict, non-list, non-primitive values to strings
            self._sanitize_for_toml(self.data)

            with open(file_path, 'w', encoding='utf-8') as file:
                toml.dump(self.data, file)
            self.logger.info(f"Saved data to {file_path}")

            # Perform round-trip comparison for keys with 'new' field
            self._remove_identical_new_values(file_path)

            # Apply TOML section reordering to ensure _meta is at the front
            self._reorder_toml_sections(file_path)

        except Exception as e:
            self.logger.error(f"Error saving data to {file_path}: {e}")
    
    def _sanitize_for_toml(self, data: dict) -> None:
        """
        Recursively sanitize data to ensure TOML compatibility.
        Converts any non-standard values (e.g. lists at entry level) to
        TOML-compatible structures to prevent 'list index out of range' errors.
        """
        for key, value in list(data.items()):
            if isinstance(value, dict):
                self._sanitize_for_toml(value)
            elif isinstance(value, list):
                # Lists are valid in TOML, but ensure contents are primitives
                pass
            elif isinstance(value, (str, int, float, bool)):
                pass
            elif value is None:
                self.logger.warning(f"Converting None value for key '{key}' to empty string")
                data[key] = ""
            else:
                self.logger.warning(f"Converting non-TOML value type {type(value).__name__} for key '{key}' to string")
                data[key] = str(value)

    def _reorder_toml_sections(self, file_path: str) -> None:
        """
        重新排序TOML文件，确保_meta section在最前面
        """
        try:
            from .reorder import reorder_toml_sections
            
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as file:
                toml_content = file.read()
            
            # 重新排序
            reordered_content = reorder_toml_sections(toml_content)
            
            # 如果内容有变化，重新写入文件
            if reordered_content != toml_content:
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(reordered_content)
                self.logger.info(f"Reordered TOML sections in {file_path} (_meta sections moved to front)")
            
        except Exception as e:
            self.logger.warning(f"Failed to reorder TOML sections in {file_path}: {e}")
    
    def _remove_identical_new_values(self, file_path: str) -> None:
        """
        Read back the saved TOML file and compare 'new' and 'raw' values.
        If they are identical after TOML round-trip, remove the 'new' field.
        """
        try:
            # Read back the file
            with open(file_path, 'r', encoding='utf-8') as file:
                saved_data = toml.load(file, _dict=OrderedDict)
            
            modified = False
            for key in saved_data:
                if key == '_meta':
                    continue
                entry = saved_data[key]
                if isinstance(entry, dict) and 'new' in entry and 'raw' in entry:
                    # Compare after round-trip
                    if entry['new'] == entry['raw']:
                        del entry['new']
                        modified = True
                        self.logger.info(f"Removed 'new' field for key '{key}': identical to 'raw' after TOML round-trip")
            
            # Save back if modified
            if modified:
                with open(file_path, 'w', encoding='utf-8') as file:
                    toml.dump(saved_data, file)
                self.logger.info(f"Updated {file_path} after round-trip comparison")
        except Exception as e:
            self.logger.error(f"Error in round-trip comparison for {file_path}: {e}")

    def update_data(self) -> None:
        """
        Update data according to v3 requirements:
        - Add/update '_meta' section with 'name' and 'field_prompt' fields, preserve other _meta subfields
        - For new keys: create with 'new' field only
        - For existing keys with changed raw: add 'new' field alongside existing data
        - For unchanged keys: keep as-is
        - Preserve 'prompt' fields in individual entries
        - If data acquisition fails (empty new_raw_data), preserve existing _meta completely
        """
        self.data = OrderedDict()
        
        # Handle _meta section for metadata
        if '_meta' in self.old_data and isinstance(self.old_data['_meta'], dict):
            # Start with existing _meta data to preserve all subfields
            self.data['_meta'] = OrderedDict(self.old_data['_meta'])
        else:
            # Create new _meta section if it doesn't exist
            self.data['_meta'] = OrderedDict()
        
        # Only update basic _meta fields if we have new data or are creating for the first time
        if len(self.new_raw_data) > 0 or '_meta' not in self.old_data:
            # Update name (always set to current mod name)
            self.data['_meta']['name'] = self.name
            
            # Preserve field_prompt if it exists in old data
            if 'field_prompt' in self.old_data:
                self.data['_meta']['field_prompt'] = self.old_data['field_prompt']
            elif '_meta' not in self.old_data or 'field_prompt' not in self.data['_meta']:
                # Don't override existing field_prompt if it exists in _meta
                pass
        else:
            # Data acquisition failed, keep existing _meta as-is
            self.logger.info(f"Data acquisition failed for mod {self.id}, preserving existing _meta fields")
        
        # If data acquisition failed (no new raw data), preserve all existing data
        if len(self.new_raw_data) == 0:
            self.logger.warning(f"No new raw data for mod {self.id}, preserving all existing data")
            # Copy all existing data (except what we've already handled in _meta)
            for key in self.old_data:
                if key not in ['name', 'field_prompt'] and key not in self.data:
                    self.data[key] = self.old_data[key]
                    self.logger.debug(f"Preserved existing key '{key}' due to data acquisition failure")
            return  # Skip all processing since we have no new data
        
        # Process each key from raw data
        for key, new_value in self.new_raw_data.items():
            # Check both regular key and _meta section for existing data
            if key in self.old_data and isinstance(self.old_data[key], dict):
                # Key exists in old data
                old_entry = self.old_data[key]
                self.data[key] = OrderedDict()
                
                # Check if raw value changed
                old_raw = old_entry.get('raw', '')
                
                if old_raw != new_value:
                    # Value changed - add 'new' field
                    # Copy all existing fields except old 'new' field
                    temp_entry = OrderedDict()
                    for field, value in old_entry.items():
                        if field != 'new':
                            temp_entry[field] = value
                    
                    # Add 'new' field to indicate retranslation needed
                    temp_entry['new'] = new_value
                    
                    # Ensure status field exists (keep existing or set to "normal")
                    if 'status' not in temp_entry:
                        temp_entry['status'] = 'normal'
                    
                    # Reorder fields: raw, new, status, language codes
                    self.data[key] = reorder_entry_fields(temp_entry)
                    
                    self.logger.info(f"Updated key '{key}': value changed from '{old_raw}' to '{new_value}'")
                else:
                    # Value unchanged - keep as-is, but ensure status and reorder fields
                    temp_entry = old_entry.copy()
                    if 'status' not in temp_entry:
                        temp_entry['status'] = 'normal'
                    self.data[key] = reorder_entry_fields(temp_entry)
            else:
                # New key - create with 'new' field and status
                self.data[key] = OrderedDict()
                self.data[key]['new'] = new_value
                self.data[key]['status'] = 'normal'
                self.logger.info(f"New key '{key}' added with value '{new_value}'")
        
        # Preserve keys from old data that are not in new raw data
        # Set status field based on whether key was from older version
        for key in self.old_data:
            if key not in ['name', 'field_prompt', '_meta'] and key not in self.data:
                old_entry = self.old_data[key]
                if isinstance(old_entry, dict):
                    # Check if this key already has status "old" (from older version)
                    if old_entry.get('status') != 'old':
                        # This key was in the latest version but no longer exists in raw data
                        # Set status to "abandoned"
                        entry_copy = OrderedDict(old_entry)
                        entry_copy['status'] = 'abandoned'
                        self.data[key] = reorder_entry_fields(entry_copy)
                        self.logger.info(f"Key '{key}' status: abandoned (no longer in raw data)")
                    else:
                        # This key was from an older version, keep as-is with status "old"
                        self.data[key] = reorder_entry_fields(old_entry)
                        self.logger.debug(f"Preserved old key '{key}' from older version (status: old)")
                else:
                    self.data[key] = old_entry
                    self.logger.debug(f"Preserved key '{key}' (not in new raw data)")
