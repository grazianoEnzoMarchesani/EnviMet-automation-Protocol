# -*- coding: utf-8 -*-
"""
EnviProtocol Dashboard - Simple Plants Customization Dialog
Allows mapping ESA classes and Forest Undergrowth to ENVI-met Simple Plant IDs.
"""

import os
import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QComboBox, QPushButton, QLabel,
    QHeaderView, QTabWidget, QWidget, QFormLayout, QSpinBox, QDoubleSpinBox,
    QCheckBox
)
from ...core.constants import ESA_SIMPLE_PLANT_MAPPING

class PlantCustomizationDialog(QDialog):
    """Dialog to allow users to customize Vegetation (Simple Plants & 3D Trees)."""
    
    def __init__(self, current_mapping=None, current_tree_settings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Personalizza Vegetazione")
        self.resize(550, 550)
        
        # Simple Plants mapping
        self.mapping = current_mapping.copy() if current_mapping else ESA_SIMPLE_PLANT_MAPPING.copy()
        if "TCD_UNDERgrowth" not in self.mapping:
            self.mapping["TCD_UNDERgrowth"] = "0200XX"
        
        # 3D Tree settings
        self.tree_settings = current_tree_settings.copy() if current_tree_settings else {
            "type": "Deciduous Trees",
            "shape": "Random",
            "density_mode": "auto",
            "tcd_threshold": 70,
            "density_multiplier": 1.0,
            "exclude_barren_water": True,
            "exclude_grassland": True,
            "envimet_v6": True
        }
        if "envimet_v6" not in self.tree_settings:
            self.tree_settings["envimet_v6"] = True
        
        # Load database to get all simple plant options
        self.plant_options = self._load_plant_options()
        
        self._setup_ui()
        self._load_data()

    def _load_plant_options(self):
        """Loads all available simple plants from envimet_db.json."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "envimet_db.json")
        options = []
        try:
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                
                for cat, items in db.get("simple_plants", {}).items():
                    for item in items:
                        options.append((item["envi_id"], item["name"], cat))
        except Exception:
            pass
        return sorted(options, key=lambda x: (x[2], x[1]))

    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        
        # Tabs
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        # --- TAB 1: Simple Plants ---
        self.tab_simple = QWidget()
        self.simple_layout = QVBoxLayout(self.tab_simple)
        
        self.info_label = QLabel(
            "Associa le classi di copertura del suolo (ESA) o il sottobosco (TCD) ai tipi di 'Simple Plant' ENVI-met.\n"
            "Queste sono superfici piane o piccoli arbusti."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("margin-bottom: 5px; color: #555; font-size: 11px;")
        self.simple_layout.addWidget(self.info_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Sorgente (ESA / TCD)", "Pianta ENVI-met"])
        
        # QGIS 4 (PyQt6) compatibility for enums
        if hasattr(QHeaderView, 'ResizeToContents'):
            mode_resize = QHeaderView.ResizeToContents
            mode_stretch = QHeaderView.Stretch
        else:
            mode_resize = QHeaderView.ResizeMode.ResizeToContents
            mode_stretch = QHeaderView.ResizeMode.Stretch

        self.table.horizontalHeader().setSectionResizeMode(0, mode_resize)
        self.table.horizontalHeader().setSectionResizeMode(1, mode_stretch)
        self.simple_layout.addWidget(self.table)
        
        self.tabs.addTab(self.tab_simple, "Simple Plants (Superfici)")
        
        # --- TAB 2: 3D Trees ---
        self.tab_3d = QWidget()
        self.tree_layout = QVBoxLayout(self.tab_3d)
        
        self.tree_info = QLabel(
            "Configura come assegnare gli ID agli alberi 3D generati dal TCD (densità) e ETH (altezza).\n"
            "Il sistema sceglierà automaticamente la taglia (Small/Medium/Large) in base ai dati ETH."
        )
        self.tree_info.setWordWrap(True)
        self.tree_info.setStyleSheet("margin-bottom: 10px; color: #555; font-size: 11px;")
        self.tree_layout.addWidget(self.tree_info)
        
        self.tree_form = QFormLayout()
        
        # 0. ENVI-met 6 Catalog Toggle
        self.chk_envimet_v6 = QCheckBox("Usa catalogo piante 3D ENVI-met 6 (Abstract aggiornate)")
        self.chk_envimet_v6.setToolTip(
            "Se attivo, utilizza esclusivamente le nuove piante 3D Abstract di ENVI-met 6\n"
            "(Small 5m, Regular 10m, Medium 15m, Large 20m) escludendo i vecchi ID rimossi."
        )
        self.chk_envimet_v6.setChecked(self.tree_settings.get("envimet_v6", True))
        self.chk_envimet_v6.toggled.connect(lambda _: self._update_shape_options(self.combo_type.currentText()))
        self.tree_form.addRow(self.chk_envimet_v6)
        
        # 1. Tree Type
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Deciduous Trees", "Conifers", "Palm Trees"])
        self.combo_type.setCurrentText(self.tree_settings.get("type", "Deciduous Trees"))
        self.combo_type.currentTextChanged.connect(self._update_shape_options)
        self.tree_form.addRow("Tipologia prevalente (Abstract):", self.combo_type)

        # 1b. Tree Shape
        self.combo_shape = QComboBox()
        self._update_shape_options(self.combo_type.currentText())
        pref_shape = self.tree_settings.get("shape", "Random")
        idx_s = self.combo_shape.findText(pref_shape)
        if idx_s >= 0: self.combo_shape.setCurrentIndex(idx_s)
        self.tree_form.addRow("Forma della chioma (Shape):", self.combo_shape)
        
        # 2. Density Mode
        self.combo_density = QComboBox()
        self.combo_density.addItem("Auto (Usa dati TCD)", "auto")
        self.combo_density.addItem("Sempre Denso (Dense)", "dense")
        self.combo_density.addItem("Sempre Rado (Sparse)", "sparse")
        idx_d = self.combo_density.findData(self.tree_settings.get("density_mode", "auto"))
        self.combo_density.setCurrentIndex(idx_d if idx_d >= 0 else 0)
        self.tree_form.addRow("Densità chioma:", self.combo_density)
        
        # 3. TCD Threshold
        self.spin_tcd = QSpinBox()
        self.spin_tcd.setRange(0, 100)
        self.spin_tcd.setSuffix("%")
        self.spin_tcd.setValue(self.tree_settings.get("tcd_threshold", 70))
        self.tree_form.addRow("Soglia per chioma fitta (TCD > %):", self.spin_tcd)
        
        # 4. Density Multiplier
        self.spin_mult = QDoubleSpinBox()
        self.spin_mult.setRange(0.1, 10.0)
        self.spin_mult.setSingleStep(0.5)
        self.spin_mult.setSuffix("x")
        self.spin_mult.setValue(self.tree_settings.get("density_multiplier", 1.0))
        self.tree_form.addRow("Moltiplicatore Densità (Turbo):", self.spin_mult)
        
        # 5. Exclude Barren & Water
        self.chk_exclude_barren = QCheckBox("Escludi aree sterili/sabbia e acqua (ESA 60, 70, 80)")
        self.chk_exclude_barren.setToolTip("Evita la generazione di alberi su spiagge (sabbia), roccia nuda o specchi d'acqua dovuta a falsi positivi.")
        self.chk_exclude_barren.setChecked(self.tree_settings.get("exclude_barren_water", True))
        self.tree_form.addRow(self.chk_exclude_barren)
        
        # 6. Exclude Grassland
        self.chk_exclude_grassland = QCheckBox("Escludi aree a prato / grassland (ESA 30)")
        self.chk_exclude_grassland.setToolTip("Evita la generazione di alberi su campi sportivi, prati e altre aree erbose aperte mappate come grassland.")
        self.chk_exclude_grassland.setChecked(self.tree_settings.get("exclude_grassland", True))
        self.tree_form.addRow(self.chk_exclude_grassland)
        
        self.tree_layout.addLayout(self.tree_form)
        self.tree_layout.addStretch()
        
        self.tabs.addTab(self.tab_3d, "Piante 3D (Alberi)")
        
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
        """Populates the table and fields with settings."""
        sources = [
            ("TCD_UNDERgrowth", "Sottobosco (aree con alberi da TCD)"),
            (20, "Arbusti / Shrubland (ESA 20)"),
            (30, "Prati / Grassland (ESA 30)"),
            (40, "Coltivazioni / Cropland (ESA 40)"),
            (90, "Zone Umide / Herbaceous wetland (ESA 90)"),
            (100, "Muschi e Licheni (ESA 100)")
        ]
        
        self.table.setRowCount(len(sources))
        for row, (key, display_name) in enumerate(sources):
            item_src = QTableWidgetItem(display_name)
            item_src.setFlags(Qt.ItemIsEnabled)
            item_src.setData(Qt.UserRole, key)
            self.table.setItem(row, 0, item_src)
            
            combo = QComboBox()
            current_id = self.mapping.get(key)
            default_idx = 0
            for idx, (p_id, p_name, p_cat) in enumerate(self.plant_options):
                combo.addItem(f"[{p_cat}] {p_name} ({p_id})", p_id)
                if p_id == current_id:
                    default_idx = idx
            combo.setCurrentIndex(default_idx)
            self.table.setCellWidget(row, 1, combo)

    def _update_shape_options(self, tree_type):
        """Update shape options based on the tree type and ENVI-met version."""
        current_shape = self.combo_shape.currentText() if hasattr(self, "combo_shape") else ""
        self.combo_shape.clear()
        use_v6 = self.chk_envimet_v6.isChecked() if hasattr(self, "chk_envimet_v6") else True
        if tree_type == "Deciduous Trees":
            if use_v6:
                self.combo_shape.addItems(["Random", "Cylindric", "Spherical"])
            else:
                self.combo_shape.addItems(["Random", "Cylindric", "Heart-shaped", "Spherical"])
        elif tree_type == "Conifers":
            self.combo_shape.addItems(["Random", "Conic", "Cylindric"])
        else: # Palm Trees
            self.combo_shape.addItems(["Palm"])
        idx = self.combo_shape.findText(current_shape)
        if idx >= 0:
            self.combo_shape.setCurrentIndex(idx)

    def _reset_to_defaults(self):
        """Reset internal mapping and reload table."""
        self.mapping = ESA_SIMPLE_PLANT_MAPPING.copy()
        if "TCD_UNDERgrowth" not in self.mapping:
            self.mapping["TCD_UNDERgrowth"] = "0200XX"
        self.tree_settings = {
            "type": "Deciduous Trees",
            "shape": "Random",
            "density_mode": "auto",
            "tcd_threshold": 70,
            "density_multiplier": 1.0,
            "exclude_barren_water": True,
            "exclude_grassland": True,
            "envimet_v6": True
        }
        self.chk_envimet_v6.setChecked(True)
        self.combo_type.setCurrentText("Deciduous Trees")
        self._update_shape_options("Deciduous Trees")
        self.combo_shape.setCurrentText("Random")
        self.combo_density.setCurrentIndex(0)
        self.spin_tcd.setValue(70)
        self.spin_mult.setValue(1.0)
        self.chk_exclude_barren.setChecked(True)
        self.chk_exclude_grassland.setChecked(True)
        self._load_data()

    def get_settings(self):
        """Returns (simple_plant_mapping, tree_settings)."""
        new_mapping = {}
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).data(Qt.UserRole)
            combo = self.table.cellWidget(row, 1)
            new_mapping[key] = combo.currentData()
        
        new_tree_settings = {
            "type": self.combo_type.currentText(),
            "shape": self.combo_shape.currentText(),
            "density_mode": self.combo_density.currentData(),
            "tcd_threshold": self.spin_tcd.value(),
            "density_multiplier": self.spin_mult.value(),
            "exclude_barren_water": self.chk_exclude_barren.isChecked(),
            "exclude_grassland": self.chk_exclude_grassland.isChecked(),
            "envimet_v6": self.chk_envimet_v6.isChecked()
        }
        return new_mapping, new_tree_settings
