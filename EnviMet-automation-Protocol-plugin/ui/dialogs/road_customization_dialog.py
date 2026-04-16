# -*- coding: utf-8 -*-

import os
import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QComboBox, QPushButton, QLabel,
    QHeaderView, QDoubleSpinBox
)
from ...core.constants import ROAD_WIDTH_MAPPING, ROAD_MATERIAL_MAPPING

class RoadCustomizationDialog(QDialog):
    """Dialog to allow users to customize OSM Road widths and materials."""
    
    def __init__(self, current_widths=None, current_materials=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Personalizza Rete Stradale OSM")
        self.resize(600, 500)
        
        # Original/Default mappings
        self.widths = current_widths.copy() if current_widths else ROAD_WIDTH_MAPPING.copy()
        self.materials = current_materials.copy() if current_materials else ROAD_MATERIAL_MAPPING.copy()
        
        # Load database to get all material options
        self.soil_options = self._load_soil_options()
        
        self._setup_ui()
        self._load_data()

    def _load_soil_options(self):
        """Loads all available soil profiles from envimet_db.json."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "envimet_db.json")
        options = []
        try:
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                
                for cat, items in db.get("soil_profiles", {}).items():
                    for item in items:
                        options.append((item["envi_id"], item["name"]))
        except Exception:
            pass
        return sorted(options, key=lambda x: x[1])

    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        
        self.info_label = QLabel(
            "Configura lo spessore reale (buffer) e il materiale ENVI-met per ogni categoria stradale OSM."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("margin-bottom: 10px; color: #555;")
        self.layout.addWidget(self.info_label)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Categoria OSM", "Larghezza Totale (m)", "Materiale ENVI-met"])
        
        # QGIS 4 (PyQt6) compatibility for enums
        if hasattr(QHeaderView, 'ResizeToContents'):
            mode_resize = QHeaderView.ResizeToContents
            mode_stretch = QHeaderView.Stretch
        else:
            mode_resize = QHeaderView.ResizeMode.ResizeToContents
            mode_stretch = QHeaderView.ResizeMode.Stretch

        self.table.horizontalHeader().setSectionResizeMode(0, mode_resize)
        self.table.horizontalHeader().setSectionResizeMode(1, mode_resize)
        self.table.horizontalHeader().setSectionResizeMode(2, mode_stretch)
        self.layout.addWidget(self.table)
        
        # Buttons
        self.btn_layout = QHBoxLayout()
        self.btn_reset = QPushButton("Ripristina Predefiniti")
        self.btn_ok = QPushButton("Conferma")
        self.btn_cancel = QPushButton("Annulla")
        
        self.btn_layout.addWidget(self.btn_reset)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_cancel)
        self.btn_layout.addWidget(self.btn_ok)
        self.layout.addLayout(self.btn_layout)
        
        # Connections
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_reset.clicked.connect(self._reset_to_defaults)

    def _load_data(self):
        """Populates the table with road categories and current settings."""
        categories = sorted(self.widths.keys())
        # Ensure 'default' is at the end if it exists
        if "default" in categories:
            categories.remove("default")
            categories.append("default")
            
        self.table.setRowCount(len(categories))
        
        for row, cat in enumerate(categories):
            # Col 0: OSM Category
            item_cat = QTableWidgetItem(cat.capitalize())
            item_cat.setFlags(Qt.ItemIsEnabled)
            item_cat.setData(Qt.UserRole, cat)
            self.table.setItem(row, 0, item_cat)
            
            # Col 1: Width (SpinBox)
            width_spin = QDoubleSpinBox()
            width_spin.setRange(0.5, 50.0)
            width_spin.setSingleStep(0.5)
            width_spin.setValue(self.widths.get(cat, 4.0))
            width_spin.setSuffix(" m")
            self.table.setCellWidget(row, 1, width_spin)
            
            # Col 2: ENVI-met Material (ComboBox)
            combo = QComboBox()
            current_id = self.materials.get(cat, "0200ST")
            
            default_idx = 0
            for idx, (env_id, env_name) in enumerate(self.soil_options):
                combo.addItem(f"{env_name} ({env_id})", env_id)
                if env_id == current_id:
                    default_idx = idx
            
            combo.setCurrentIndex(default_idx)
            self.table.setCellWidget(row, 1, width_spin) # Already set above
            self.table.setCellWidget(row, 2, combo)

    def _reset_to_defaults(self):
        """Reset internal mapping and reload table."""
        self.widths = ROAD_WIDTH_MAPPING.copy()
        self.materials = ROAD_MATERIAL_MAPPING.copy()
        self._load_data()

    def get_settings(self):
        """Returns the widths and materials defined by the user."""
        new_widths = {}
        new_materials = {}
        for row in range(self.table.rowCount()):
            cat = self.table.item(row, 0).data(Qt.UserRole)
            width_spin = self.table.cellWidget(row, 1)
            combo = self.table.cellWidget(row, 2)
            
            new_widths[cat] = width_spin.value()
            new_materials[cat] = combo.currentData()
            
        return new_widths, new_materials
