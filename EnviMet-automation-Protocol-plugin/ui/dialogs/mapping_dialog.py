# -*- coding: utf-8 -*-

import os
import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QComboBox, QPushButton, QLabel,
    QHeaderView
)
from ...core.constants import ESA_ENVIMET_MAPPING

class MappingCustomizationDialog(QDialog):
    """Dialog to allow users to customize ESA -> ENVI-met material mapping."""
    
    def __init__(self, current_mapping=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Personalizza Mapping Materiali ESA")
        self.resize(500, 600)
        
        # Original/Default mapping from constants if None
        self.mapping = current_mapping.copy() if current_mapping else ESA_ENVIMET_MAPPING.copy()
        
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
            "Associa le classi ESA WorldCover ai profili di suolo di ENVI-met.\n"
            "Le modifiche verranno applicate alla prossima elaborazione."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("margin-bottom: 10px; color: #555;")
        self.layout.addWidget(self.info_label)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Classe ESA (Land Use)", "Materiale ENVI-met"])
        
        # QGIS 4 (PyQt6) compatibility for enums
        if hasattr(QHeaderView, 'ResizeToContents'):
            mode_resize = QHeaderView.ResizeToContents
            mode_stretch = QHeaderView.Stretch
        else:
            mode_resize = QHeaderView.ResizeMode.ResizeToContents
            mode_stretch = QHeaderView.ResizeMode.Stretch

        self.table.horizontalHeader().setSectionResizeMode(0, mode_resize)
        self.table.horizontalHeader().setSectionResizeMode(1, mode_stretch)
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
        """Populates the table with ESA classes and current mappings."""
        esa_names = {
            10: "Tree cover",
            20: "Shrubland",
            30: "Grassland",
            40: "Cropland",
            50: "Built-up (Pavements/Yards)",
            60: "Bare / sparse vegetation",
            70: "Snow and Ice",
            80: "Permanent water bodies",
            90: "Herbaceous wetland",
            95: "Mangroves",
            100: "Moss and lichen"
        }
        
        self.table.setRowCount(len(esa_names))
        
        for row, (dn, name) in enumerate(sorted(esa_names.items())):
            # Col 0: ESA Class
            item_esa = QTableWidgetItem(name)
            item_esa.setFlags(Qt.ItemIsEnabled)
            item_esa.setData(Qt.UserRole, dn)
            self.table.setItem(row, 0, item_esa)
            
            # Col 1: ENVI-met Material
            combo = QComboBox()
            current_id = self.mapping.get(dn)
            
            default_idx = 0
            for idx, (env_id, env_name) in enumerate(self.soil_options):
                combo.addItem(f"{env_name} ({env_id})", env_id)
                if env_id == current_id:
                    default_idx = idx
            
            combo.setCurrentIndex(default_idx)
            self.table.setCellWidget(row, 1, combo)

    def _reset_to_defaults(self):
        """Reset internal mapping and reload table."""
        self.mapping = ESA_ENVIMET_MAPPING.copy()
        self._load_data()

    def get_mapping(self):
        """Returns the mapping dictionary defined by the user."""
        new_mapping = {}
        for row in range(self.table.rowCount()):
            dn = self.table.item(row, 0).data(Qt.UserRole)
            combo = self.table.cellWidget(row, 1)
            new_mapping[dn] = combo.currentData()
        return new_mapping
