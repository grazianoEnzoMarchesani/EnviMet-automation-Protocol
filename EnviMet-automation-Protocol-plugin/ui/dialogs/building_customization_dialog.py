# -*- coding: utf-8 -*-
"""
EnviProtocol - Building Customization Dialog
Allows users to set ENVI-met IDs for Walls, Roofs and Greenings.
"""

import os
import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, 
    QPushButton, QLabel, QGroupBox, QFormLayout
)
from ...core.constants import (
    BUILDING_WALL_MATERIAL_DEFAULT, BUILDING_ROOF_MATERIAL_DEFAULT,
    BUILDING_WALL_GREENING_DEFAULT, BUILDING_ROOF_GREENING_DEFAULT
)

class BuildingCustomizationDialog(QDialog):
    """Dialog to customize building materials and greening profiles."""
    
    def __init__(self, current_settings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurazione Materiali Edifici")
        self.resize(450, 350)
        
        # Load defaults if no settings provided
        self.settings = current_settings if current_settings else {
            "wall_id": BUILDING_WALL_MATERIAL_DEFAULT,
            "roof_id": BUILDING_ROOF_MATERIAL_DEFAULT,
            "wall_green_id": BUILDING_WALL_GREENING_DEFAULT,
            "roof_green_id": BUILDING_ROOF_GREENING_DEFAULT
        }
        
        # Load database options
        self.material_options = self._load_db_options("wall_roof_constructions")
        self.greening_options = self._load_db_options("greenings")
        
        # Add "None" option to greening
        self.greening_options.insert(0, ("", "--- Nessun Verde ---"))
        
        self._setup_ui()

    def _load_db_options(self, category):
        """Loads available options from envimet_db.json for a specific category."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "envimet_db.json")
        options = []
        try:
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                
                cat_data = db.get(category, {})
                for group, items in cat_data.items():
                    for item in items:
                        options.append((item["envi_id"], f"{item['name']}"))
        except Exception:
            pass
        return sorted(options, key=lambda x: x[1])

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        info = QLabel(
            "Seleziona i profili costruttivi e di vegetazione predefiniti per gli edifici.\n"
            "Questi ID verranno assegnati a tutti gli edifici nell'area di studio."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; margin-bottom: 10px;")
        layout.addWidget(info)
        
        # 1. Materials Group
        mat_group = QGroupBox("Materiali Costruttivi")
        mat_layout = QFormLayout(mat_group)
        
        self.combo_wall = QComboBox()
        self.combo_roof = QComboBox()
        
        for eid, name in self.material_options:
            self.combo_wall.addItem(f"{name} ({eid})", eid)
            self.combo_roof.addItem(f"{name} ({eid})", eid)
            
        mat_layout.addRow("Mura [ENVI_ID]:", self.combo_wall)
        mat_layout.addRow("Tetto [ENVI_ID]:", self.combo_roof)
        layout.addWidget(mat_group)
        
        # 2. Greening Group
        green_group = QGroupBox("Verde Pensile / Verticale")
        green_layout = QFormLayout(green_group)
        
        self.combo_w_green = QComboBox()
        self.combo_r_green = QComboBox()
        
        for eid, name in self.greening_options:
            self.combo_w_green.addItem(f"{name} ({eid})".replace(" ()", ""), eid)
            self.combo_r_green.addItem(f"{name} ({eid})".replace(" ()", ""), eid)
            
        green_layout.addRow("Verde Verticale:", self.combo_w_green)
        green_layout.addRow("Verde Orizzontale:", self.combo_r_green)
        layout.addWidget(green_group)
        
        # Set current values
        self._set_current_combos()
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_reset = QPushButton("Ripristina Predefiniti")
        self.btn_ok = QPushButton("Conferma")
        self.btn_cancel = QPushButton("Annulla")
        
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)
        
        # Connections
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_reset.clicked.connect(self._reset_to_defaults)

    def _set_current_combos(self):
        """Sets combo boxes to current settings."""
        self._set_combo_value(self.combo_wall, self.settings["wall_id"])
        self._set_combo_value(self.combo_roof, self.settings["roof_id"])
        self._set_combo_value(self.combo_w_green, self.settings["wall_green_id"])
        self._set_combo_value(self.combo_r_green, self.settings["roof_green_id"])

    def _set_combo_value(self, combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentIndex(0)

    def _reset_to_defaults(self):
        """Reset settings to hardcoded defaults."""
        self._set_combo_value(self.combo_wall, BUILDING_WALL_MATERIAL_DEFAULT)
        self._set_combo_value(self.combo_roof, BUILDING_ROOF_MATERIAL_DEFAULT)
        self._set_combo_value(self.combo_w_green, BUILDING_WALL_GREENING_DEFAULT)
        self._set_combo_value(self.combo_r_green, BUILDING_ROOF_GREENING_DEFAULT)

    def get_settings(self):
        """Returns the dictionary of settings."""
        return {
            "wall_id": self.combo_wall.currentData(),
            "roof_id": self.combo_roof.currentData(),
            "wall_green_id": self.combo_w_green.currentData(),
            "roof_green_id": self.combo_r_green.currentData()
        }
