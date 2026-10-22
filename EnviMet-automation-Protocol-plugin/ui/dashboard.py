# -*- coding: utf-8 -*-
"""
EnviProtocol Dashboard - Main UI Module

This module contains the main EnviProtocolDashboard class for the EnviProtocol QGIS plugin.
The UI is composed of modular section widgets and mixins for better maintainability.
"""

import os
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QScrollArea, QPushButton
)
from qgis.core import QgsProject, QgsMessageLog, Qgis, QgsApplication

# Local modular imports
from ..core.data_manager import DataManager
from ..core.constants import LayerNames, FileNames
from .styles import STYLESHEET
from .tasks import (
    DownloadTask, ENVImetTask, MigrationTask
)
from .sections import (
    ProjectSetupSection, DataAcquisitionSection,
    ENVImetExportSection, SubAreaModificationSection,
    AttributeModificationSection,
    ProgressInfoSection,
    ENVImetImportSection
)

from .mixins import LayerMixin



class EnviProtocolDashboard(LayerMixin, QDockWidget):
    """Main EnviProtocol Dashboard dock widget."""
    
    closingPlugin = pyqtSignal()
    
    def __init__(self, iface, parent=None):
        super(EnviProtocolDashboard, self).__init__(parent)
        self.iface = iface
        self.data_manager = DataManager(iface)
        self.setWindowTitle("EnviProtocol Dashboard")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        # Root widget
        self.root = QWidget()
        self.root.setObjectName("DashboardRoot")
        self.root.setStyleSheet(STYLESHEET)
        self.layout = QVBoxLayout(self.root)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(0)
        
        # Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)
        
        # =====================================================
        # Create Section Widgets
        # =====================================================
        
        # Section 1: Project Setup
        self.setup_section = ProjectSetupSection(iface, self)
        self.scroll_layout.addWidget(self.setup_section)
        
        # Section 2: Data Acquisition
        self.data_section = DataAcquisitionSection(self)
        self.scroll_layout.addWidget(self.data_section)
        
        # Section 3: ENVI-met Preparation
        self.envimet_section = ENVImetExportSection(self)
        self.scroll_layout.addWidget(self.envimet_section)
        
        # Section 4: Sub-Area Modification
        self.sub_area_mod_section = SubAreaModificationSection(self)
        self.scroll_layout.addWidget(self.sub_area_mod_section)
        
        self.setup_section.extent_captured.connect(self._on_extent_captured)
        
        # Section 5: Attribute Modification
        self.attr_mod_section = AttributeModificationSection(self)
        self.scroll_layout.addWidget(self.attr_mod_section)
        
        # Section 6: ENVI-met Results Import
        self.envimet_import_section = ENVImetImportSection(self)
        self.scroll_layout.addWidget(self.envimet_import_section)
        
        

        
        # Progress & Status
        self.progress_section = ProgressInfoSection(self)
        self.scroll_layout.addStretch()
        self.layout.addWidget(self.progress_section)
        

        
        self.setWidget(self.root)
        
        # =====================================================
        # Connect Section Signals
        # Section 2: Data Acquisition
        self.data_section.download_requested.connect(self.run_downloads)
        
        # ENVI-met Integration
        self.envimet_section.conversion_requested.connect(self.run_envimet_prep)
        self.envimet_section.migration_requested.connect(self.run_project_migration)
        
        # ENVI-met Import
        self.envimet_import_section.import_requested.connect(self.run_envimet_import)
        
        # Subarea Sync
        self._syncing_subareas = False
        self.envimet_import_section.cmb_subarea.currentTextChanged.connect(self._sync_subarea_from_import)
        self.sub_area_mod_section.combo_sub_areas.currentTextChanged.connect(self._sync_subarea_from_mod)

        
        # Project signals for dynamic UI gating
        QgsProject.instance().layersAdded.connect(self.check_layers_and_update_ui)
        QgsProject.instance().layersRemoved.connect(self.check_layers_and_update_ui)
        

        
        # Initial state
        self.check_layers_and_update_ui()

    # =========================================================================
    # UI State Management
    # =========================================================================
    
    def _sync_subarea_from_import(self, text):
        if self._syncing_subareas: return
        self._syncing_subareas = True
        idx = self.sub_area_mod_section.combo_sub_areas.findText(text)
        if idx >= 0:
            self.sub_area_mod_section.combo_sub_areas.setCurrentIndex(idx)
        self._syncing_subareas = False

    def _sync_subarea_from_mod(self, text):
        if self._syncing_subareas: return
        self._syncing_subareas = True
        idx = self.envimet_import_section.cmb_subarea.findText(text)
        if idx >= 0:
            self.envimet_import_section.cmb_subarea.setCurrentIndex(idx)
        self._syncing_subareas = False
        
    def set_dashboard_enabled(self, enabled):
        """Enable or disable the entire plugin UI during background tasks."""
        self.data_section.set_enabled(enabled)
        self.envimet_section.set_enabled(enabled)
        self.sub_area_mod_section.setEnabled(enabled)
        self.attr_mod_section.setEnabled(enabled)
        self.setup_section.setEnabled(enabled)
        self.envimet_import_section.setEnabled(enabled)
        
        if not enabled:
            self.progress_section.set_status("⚠ Operazione in corso... Attendere", is_busy=True)
        else:
            self.progress_section.reset()
            self.check_layers_and_update_ui()

    def check_layers_and_update_ui(self, *args):
        """Enable or disable processing steps based on layer presence."""
        pass


    # =========================================================================
    # Task Execution Methods
    # =========================================================================

    def run_downloads(self):
        """Execute data downloads based on user selection."""
        try:
            project_path = QgsProject.instance().fileName()
            if not project_path:
                self.iface.messageBar().pushMessage(
                    "Errore", "Salva il progetto QGIS prima di procedere.", level=Qgis.Warning, duration=5
                )
                self.progress_section.set_status("⚠ Salva il progetto prima di continuare", is_error=True)
                self.setup_section.set_project_path_status(False)
                return
                
            extent, crs = self.setup_section.get_extent_and_crs()
            if extent is None or extent.isEmpty():
                self.iface.messageBar().pushMessage("EnviProtocol", "Manca l'Area di Studio (AOI). Vai in 'Project Setup' e clicca su 'Capture'!", level=Qgis.Warning)
                self.progress_section.set_status("⚠ Area di Studio non definita", is_error=True)
                return

            selected_checks = self.data_section.get_selected_sources()
            total_steps = sum(1 for val in selected_checks.values() if val)
            
            if total_steps == 0:
                self.iface.messageBar().pushMessage("EnviProtocol", "Seleziona almeno una sorgente dati (es. Tinitaly) nella sezione 'Data Acquisition'.", level=Qgis.Info)
                self.progress_section.set_status("⚠ Nessun dato selezionato", is_error=True)
                return

            tiles = self.data_manager.calculate_tinitaly_tiles(extent, crs) if selected_checks.get("Tinitaly (DTM 10m)") else []
            
            self.set_dashboard_enabled(False)
            self.progress_section.set_status("Avvio acquisizione dati in background...")
            self.progress_section.set_progress(0)
            
            task = DownloadTask(self.data_manager, selected_checks, extent, crs, tiles)
            
            def on_progress_update(step_name, step_num, total_steps, percent):
                self.progress_section.set_status(f"[{step_num}/{total_steps}] {step_name} ({percent}%)")
                self.progress_section.set_progress(percent)
            
            def on_finished(success):
                self.set_dashboard_enabled(True)
                self.progress_section.set_progress(100 if success else 0)
                
                if success:
                    self.progress_section.set_status("✓ Acquisizione dati completata.")
                    if task.error_count == 0:
                        self.iface.messageBar().pushMessage("EnviProtocol", "Download dati completato con successo!", level=Qgis.Success)
                    else:
                        self.iface.messageBar().pushMessage("EnviProtocol", f"Download completato con {task.error_count} errori. Controlla il log.", level=Qgis.Warning)
                else:
                    self.progress_section.set_status(f"✗ Download interrotto: {task.message}", is_error=True)
            
            task.taskCompleted.connect(lambda: on_finished(True))
            task.taskTerminated.connect(lambda: on_finished(False))
            task.progressUpdated.connect(on_progress_update)
            
            QgsApplication.taskManager().addTask(task)
        except Exception as e:
            QgsMessageLog.logMessage(f"Eccezione imprevista in run_downloads: {e}", "EnviProtocol", Qgis.Warning)
            self.iface.messageBar().pushMessage("Errore Imprevisto", "Controlla il pannello Log dei Messaggi", level=Qgis.Warning)
            self.set_dashboard_enabled(True)

    def _on_extent_captured(self, extent, crs):
        """Reset stale sub-area state in RAM whenever a new extent is captured."""
        if hasattr(self, 'sub_area_mod_section') and self.sub_area_mod_section:
            self.sub_area_mod_section.sub_area_state = None

    def run_envimet_prep(self):
        """Execute the ENVI-met data preparation task."""
        try:
            extent, crs = self.setup_section.get_extent_and_crs()
            if extent is None:
                self.iface.messageBar().pushMessage("Errore", "Definisci l'AOI prima di procedere.", level=Qgis.Warning)
                return

            self.set_dashboard_enabled(False)
            self.progress_section.set_status("Preparazione dati ENVI-met in corso...")
            self.progress_section.set_progress(0)
            
            # Collect custom mappings from UI
            mapping = self.envimet_section.get_landuse_mapping()
            r_widths, r_materials = self.envimet_section.get_road_settings()
            p_mapping = self.envimet_section.get_plant_mapping()
            t_settings = self.envimet_section.get_tree_settings()
            b_settings = self.envimet_section.get_building_settings()
            do_lev = self.envimet_section.is_leveling_enabled()
            sub_geom = self.sub_area_mod_section.get_sub_area_geometry()
            if sub_geom and not sub_geom.isEmpty():
                if not extent.intersects(sub_geom.boundingBox()):
                    QgsMessageLog.logMessage(
                        "Avviso: Geometria Sub-Area in memoria fuori dall'AOI corrente. Reset della Sub-Area all'AOI corrente.",
                        "EnviProtocol", Qgis.Warning
                    )
                    sub_geom = None
                    if hasattr(self.sub_area_mod_section, 'sub_area_state'):
                        self.sub_area_mod_section.sub_area_state = None
            sub_name = self.sub_area_mod_section.get_active_sub_area_name()
            sub_params = self.sub_area_mod_section.get_active_sub_area_params()
            
            # Prepare the sub-area synchronously in the main thread to avoid background thread locks and crashes.
            project_path = QgsProject.instance().fileName()
            if project_path:
                project_dir = os.path.dirname(project_path)
                data_dir_name = self.data_manager.get_data_dir_name()
                root_data_dir = os.path.join(project_dir, data_dir_name)
                from ..core.constants import FolderNames
                export_dir = os.path.join(root_data_dir, FolderNames.ENVIMET)
                if not os.path.exists(export_dir):
                    os.makedirs(export_dir)
                file_name = "sub_area.gpkg" if sub_name == "default" else f"sub_area_{sub_name}.gpkg"
                subarea_path = os.path.join(export_dir, file_name)
                
                from ..core.envimet_manager import ENVImetManager
                em_manager = ENVImetManager(self.iface)
                margin, suggested_z, max_h, max_z = em_manager.get_model_constraints(root_data_dir)
                crs_id = crs if isinstance(crs, str) else crs.authid()
                
                w = sub_params.get("width", 0.0) if sub_params else 0.0
                h = sub_params.get("height", 0.0) if sub_params else 0.0
                rot = sub_params.get("rotation", 0.0) if sub_params else 0.0
                gs = sub_params.get("grid_size", 0.0) if sub_params else 0.0
                
                ok, msg = em_manager.prepare_sub_area(
                    extent, crs_id, subarea_path, margin=margin, geometry=sub_geom,
                    name=sub_name, width=w, height=h, rotation=rot, grid_size=gs
                )
                if not ok:
                    QgsMessageLog.logMessage(f"Avviso preparazione sub-area nel thread principale: {msg}", "EnviProtocol", Qgis.Warning)
            
            task = ENVImetTask(
                self.data_manager, extent, crs, 
                landuse_mapping=mapping,
                road_widths=r_widths, 
                road_materials=r_materials,
                plant_mapping=p_mapping,
                tree_settings=t_settings,
                building_settings=b_settings,
                do_leveling=do_lev,
                sub_area_geometry=sub_geom,
                sub_area_name=sub_name,
                sub_area_params=sub_params
            )
            
            def on_progress_changed(percent):
                self.progress_section.set_progress(int(percent))
                # Set dynamic text description based on percentage
                if percent < 20: desc = "Analisi vincoli..."
                elif percent < 40: desc = "Preparazione Sub Area..."
                elif percent < 60: desc = "Vettorializzazione Land Use..."
                elif percent < 80: desc = "Elaborazione Edifici..."
                elif percent < 90: desc = "Elaborazione DTM..."
                elif percent < 95: desc = "Elaborazione Vegetazione 3D..."
                elif percent < 100: desc = "Elaborazione Piante Semplici..."
                else: desc = "Salvataggio..."
                self.progress_section.set_status(f"Preparazione dati ENVI-met: {desc} ({int(percent)}%)")

            def on_finished(success):
                self.set_dashboard_enabled(True)
                if success:
                    self.progress_section.set_status("✓ Dati ENVI-met pronti (cartella envimet_export).")
                    self.iface.messageBar().pushMessage("EnviProtocol", "Dati pronti per ENVI-met!", level=Qgis.Success)
                    # Automatically load/refresh layers on completion
                    self.envimet_section._load_prepared_layers()
                    self.sub_area_mod_section.load_sub_areas_from_disk()
                else:
                    msg = getattr(task, 'message', 'Errore sconosciuto')
                    self.progress_section.set_status(f"✗ Errore: {msg}", is_error=True)
                    self.iface.messageBar().pushMessage("Errore ENVI-met", msg, level=Qgis.Warning)
            
            task.taskCompleted.connect(lambda: on_finished(True))
            task.taskTerminated.connect(lambda: on_finished(False))
            task.progressChanged.connect(on_progress_changed)
            
            QgsApplication.taskManager().addTask(task)
        except Exception as e:
            QgsMessageLog.logMessage(f"Eccezione imprevista in run_envimet_prep: {e}", "EnviProtocol", Qgis.Warning)
            self.iface.messageBar().pushMessage("Errore Imprevisto", "Controlla il pannello Log dei Messaggi", level=Qgis.Warning)
            self.set_dashboard_enabled(True)

    def run_project_migration(self, target_crs_auth):
        """Execute the project CRS migration task in the background."""
        try:
            from ..core.envimet_manager import ENVImetManager
            
            self.set_dashboard_enabled(False)
            self.progress_section.set_status("Inizio migrazione CRS progetto...")
            self.progress_section.set_progress(0)
            
            manager = ENVImetManager(self.iface)
            task = MigrationTask(manager, target_crs_auth)
            
            def on_progress_changed(percent):
                self.progress_section.set_progress(int(percent))
                self.progress_section.set_status(f"Riproiezione dati al target CRS... ({int(percent)}%)")
                
            def on_finished(success):
                self.set_dashboard_enabled(True)
                self.progress_section.set_progress(100 if success else 0)
                if success:
                    self.progress_section.set_status(f"✓ Migrazione CRS completata: {task.message}")
                    self.iface.messageBar().pushMessage("EnviProtocol", f"Migrazione CRS completata! {task.message}", level=Qgis.Success)
                    # Reload the layers to reflect the new CRS
                    self.envimet_section._load_prepared_layers()
                    self.sub_area_mod_section.load_sub_areas_from_disk()
                else:
                    self.progress_section.set_status(f"✗ Errore migrazione: {task.message}", is_error=True)
                    self.iface.messageBar().pushMessage("Errore Migrazione", task.message, level=Qgis.Warning)
                    
            task.taskCompleted.connect(lambda: on_finished(True))
            task.taskTerminated.connect(lambda: on_finished(False))
            task.progressChanged.connect(on_progress_changed)
            
            QgsApplication.taskManager().addTask(task)
        except Exception as e:
            QgsMessageLog.logMessage(f"Eccezione imprevista in run_project_migration: {e}", "EnviProtocol", Qgis.Warning)
            self.iface.messageBar().pushMessage("Errore Imprevisto", "Controlla il pannello Log dei Messaggi", level=Qgis.Warning)
            self.set_dashboard_enabled(True)

    def run_envimet_import(self, edt_files, variables, heights, sub_area_geom, sub_info, crs_authid, output_dir, follow_terrain, custom_palette=""):
        """Execute the bulk ENVI-met import task."""
        from .tasks.import_task import ENVImetImportTask
        from qgis.core import QgsApplication
        
        self.set_dashboard_enabled(False)
        self.progress_section.set_status("Avvio importazione risultati ENVI-met...")
        self.progress_section.set_progress(0)
        
        task = ENVImetImportTask(edt_files, variables, heights, sub_area_geom, sub_info, crs_authid, output_dir, follow_terrain, custom_palette)
        
        def on_progress_update(step_name, step_num, total_steps, percent):
            self.progress_section.set_status(f"[{step_num}/{total_steps}] {step_name}")
            self.progress_section.set_progress(percent)
            
        def on_finished(success):
            self.set_dashboard_enabled(True)
            self.progress_section.set_progress(100 if success else 0)
            
            if success:
                self.progress_section.set_status("✓ Importazione completata.")
                if task.error_count == 0:
                    self.iface.messageBar().pushMessage("EnviProtocol", "Importazione ENVI-met completata con successo!", level=Qgis.Success)
                else:
                    self.iface.messageBar().pushMessage("EnviProtocol", f"Importazione completata con {task.error_count} errori. Controlla il log.", level=Qgis.Warning)
            else:
                self.progress_section.set_status(f"✗ Importazione fallita: {task.message}", is_error=True)
                
        task.taskCompleted.connect(lambda: on_finished(True))
        task.taskTerminated.connect(lambda: on_finished(False))
        task.progressUpdated.connect(on_progress_update)
        
        QgsApplication.taskManager().addTask(task)
