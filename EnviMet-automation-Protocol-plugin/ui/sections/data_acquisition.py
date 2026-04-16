# -*- coding: utf-8 -*-
"""
EnviProtocol Dashboard - Data Acquisition Section

Section 2: Data source selection and download controls.
Includes secure credential storage using QGIS Auth Manager.
"""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QHBoxLayout, QLabel, 
    QPushButton, QCheckBox, QLineEdit
)
from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.gui import QgsCollapsibleGroupBox

from ..mixins.help_mixin import HelpMixin
from ..help_content import HELP_DATA_ACQUISITION

from ..constants import DATA_SOURCES




class DataAcquisitionSection(QgsCollapsibleGroupBox, HelpMixin):
    """Section 2: Data Acquisition - source selection and download controls."""
    
    # Signals
    download_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("2. Data Acquisition", parent)
        self._setup_ui()
        self._connect_signals()
        
    def _setup_ui(self):
        """Initialize the UI components."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 10, 5, 10)
        self.main_layout.setSpacing(10)
        
        # Sources List
        self.sources_container = QWidget()
        self.sources_list_layout = QVBoxLayout(self.sources_container)
        self.sources_list_layout.setContentsMargins(0, 0, 0, 0)
        self.sources_list_layout.setSpacing(8) # Space between cards
        
        self.checks = {}
        
        # Source metadata for cards (Iconless minimalist version)
        SOURCE_DETAILS = {
            "Tinitaly (DTM 10m)": {
                "subtitle": "Sorgente: ISPRA / Tarquini et al. (10m)"
            },
            "TUM (Edifici H 10m)": {
                "subtitle": "Altezza edifici (TUM/WUR Global Building H)"
            },
            "ETH (Alberi H 10m)": {
                "subtitle": "Altezza della vegetazione (ETH / Lang et al.)"
            },
            "ESA WorldCover (Land Use)": {
                "subtitle": "Uso del suolo globale (10m Resolution)"
            },
            "OSM Roads (Vettoriale)": {
                "subtitle": "Rete stradale vettoriale da OpenStreetMap"
            },
            "Copernicus HRL (10m)": {
                "subtitle": "Copernicus High Resolution Layers (WAW/SBA)"
            },
            "Tree Cover Density (Copernicus)": {
                "subtitle": "Densità copertura vegetale (%) - Copernicus"
            }
        }
        
        for src in DATA_SOURCES:
            meta = SOURCE_DETAILS.get(src, {"subtitle": "Sorgente dati ambientale"})
            
            card = QWidget()
            card.setObjectName("SourceCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(15, 10, 15, 10)
            card_layout.setSpacing(10)
            
            # Text Info
            text_container = QWidget()
            text_layout = QVBoxLayout(text_container)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(2)
            
            title_label = QLabel(src)
            title_label.setObjectName("SourceTitle")
            text_layout.addWidget(title_label)
            
            sub_label = QLabel(meta["subtitle"])
            sub_label.setObjectName("SourceSubtitle")
            text_layout.addWidget(sub_label)
            
            card_layout.addWidget(text_container)
            card_layout.addStretch()
            
            # Right: Checkbox and Help
            cb = QCheckBox()
            cb.setChecked(True)
            self.checks[src] = cb
            card_layout.addWidget(cb)
            
            help_btn = self.create_help_button(src, HELP_DATA_ACQUISITION)
            help_btn.setFixedSize(18, 18)
            card_layout.addWidget(help_btn)
            
            self.sources_list_layout.addWidget(card)
            
        self.main_layout.addWidget(self.sources_container)
        
        # Download Button
        self.btn_download = QPushButton(" Download Dati Selezionati")
        self.btn_download.setObjectName("DarkButton")
        self.btn_download.setMinimumHeight(40)
        self.main_layout.addWidget(self.btn_download)
        
    def _connect_signals(self):
        """Connect UI signals to logic."""
        self.btn_download.clicked.connect(self.download_requested.emit)
        
    def get_selected_sources(self):
        """Returns a dict of {source_name: is_checked}."""
        return {src: cb.isChecked() for src, cb in self.checks.items()}
    
    def set_enabled(self, enabled):
        """Toggle section interactive state."""
        self.sources_container.setEnabled(enabled)
        self.btn_download.setEnabled(enabled)
        self.setEnabled(enabled)
