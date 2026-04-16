# -*- coding: utf-8 -*-

import os
import json
from qgis.core import QgsMessageLog, Qgis

class EnvimetDBManager:
    """
    Manager for the distilled ENVI-met local database.
    Provides methods to access soil profiles, plants, constructions, etc.
    """
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EnvimetDBManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.data = {}
        self._load_database()
        self._initialized = True

    def _load_database(self):
        """Loads the JSON database from the data directory."""
        # Get path relative to this file: core/envimet_db_manager.py -> data/envimet_db.json
        current_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(os.path.dirname(current_dir), "data", "envimet_db.json")
        
        if not os.path.exists(db_path):
            QgsMessageLog.logMessage(f"ENVI-met DB not found at {db_path}", "EnviProtocol", Qgis.Warning)
            return

        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading ENVI-met DB: {str(e)}", "EnviProtocol", Qgis.Warning)

    def get_categories(self):
        """Returns the list of top-level categories."""
        return list(self.data.keys())

    def get_subcategories(self, category_path):
        """
        Returns the subcategories for a given category path (e.g., "3d_plants/Abstract").
        Path can be a string separated by '/' or a list.
        """
        data = self._get_nested_data(category_path)
        if isinstance(data, dict):
            # Only return keys that point to dicts or lists (sub-folders or items)
            return list(data.keys())
        return []

    def get_items(self, category_path):
        """
        Returns a flat list of items for a given category path.
        If the path points to a list, it returns it.
        If it points to a dict, it flattens all lists found in its descendants.
        """
        data = self._get_nested_data(category_path)
        if not data:
            return []

        if isinstance(data, list):
            return data
        
        # If it's a dict, flatten all lists recursively
        return self._flatten_items(data)

    def _get_nested_data(self, path):
        """Helper to navigate the nested dictionary."""
        if isinstance(path, str):
            path = path.strip("/").split("/")
        
        current = self.data
        for part in path:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _flatten_items(self, data):
        """Recursively flattens all lists found in a nested dict."""
        items = []
        if isinstance(data, list):
            items.extend(data)
        elif isinstance(data, dict):
            for value in data.values():
                items.extend(self._flatten_items(value))
        return items

    def find_item_by_id(self, envi_id):
        """Searches for an item by its ENVI_ID across the whole database."""
        envi_id = envi_id.upper()
        return self._find_recursive(self.data, envi_id)

    def _find_recursive(self, data, envi_id):
        if isinstance(data, list):
            for item in data:
                if item.get("envi_id") == envi_id:
                    return item
        elif isinstance(data, dict):
            for value in data.values():
                res = self._find_recursive(value, envi_id)
                if res:
                    return res
        return None

    def search_items(self, query):
        """Searches items by name or ID (case-insensitive) across the whole database."""
        query = query.lower()
        results = []
        self._search_recursive(self.data, query, [], results)
        return results

    def _search_recursive(self, data, query, path, results):
        if isinstance(data, list):
            for item in data:
                if query in item.get("name", "").lower() or query in item.get("envi_id", "").lower():
                    results.append({
                        "path": "/".join(path),
                        "item": item
                    })
        elif isinstance(data, dict):
            for key, value in data.items():
                self._search_recursive(value, query, path + [key], results)
