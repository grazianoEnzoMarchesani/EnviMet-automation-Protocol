import os
import re
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QCheckBox, QMessageBox,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout,
    QComboBox, QInputDialog, QGridLayout, QLineEdit, QFileDialog
)
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsRasterLayer, Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox, QgsColorButton, QgsCheckableComboBox

from ..mixins.help_mixin import HelpMixin
from ..widgets.sub_area_tool import SubAreaMapTool, SubAreaStatus

class SubAreaModificationSection(QgsCollapsibleGroupBox, HelpMixin):
    """Section 4: Sub-Area Modification - Interactive geometry controls."""
    
    def __init__(self, parent=None):
        super().__init__("4. Modifica Sub-Area (Area Modello)", parent)
        
        self.sub_area_tool = None
        self.sub_area_state = None # To persist across activations
        self.sub_areas = {} # Store metadata of multiple subareas
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Initialize the UI components."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 10, 5, 10)
        self.main_layout.setSpacing(10)

        # Modifica Sub-Area Group
        self.sub_area_group = QVBoxLayout()
        self.sub_area_group.setContentsMargins(0, 0, 0, 0)
        self.sub_area_group.setSpacing(10)

        # --- GESTIONE AREE ---
        self.group_management = QGroupBox("Gestione Aree")
        self.group_management.setObjectName("SubCard")
        mgt_layout = QVBoxLayout(self.group_management)
        mgt_layout.setContentsMargins(10, 20, 10, 10)
        mgt_layout.setSpacing(8)
        
        # Row 1: Combobox & Color Button
        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("Area Attiva:"))
        self.combo_sub_areas = QComboBox()
        self.combo_sub_areas.setMinimumHeight(28)
        combo_row.addWidget(self.combo_sub_areas)
        
        self.btn_color = QgsColorButton()
        self.btn_color.setMinimumHeight(28)
        self.btn_color.setFixedWidth(60)
        self.btn_color.setShowNull(False)
        self.btn_color.setAllowOpacity(False)
        combo_row.addWidget(self.btn_color)
        
        mgt_layout.addLayout(combo_row)
        
        # Row 2: Buttons
        btn_row = QHBoxLayout()
        self.btn_new_area = QPushButton(" Nuova")
        self.btn_new_area.setObjectName("SecondaryButton")
        self.btn_new_area.setMinimumHeight(28)
        btn_row.addWidget(self.btn_new_area)
        
        self.btn_copy_area = QPushButton(" Copia")
        self.btn_copy_area.setObjectName("SecondaryButton")
        self.btn_copy_area.setMinimumHeight(28)
        btn_row.addWidget(self.btn_copy_area)
        
        self.btn_rename_area = QPushButton(" Rinomina")
        self.btn_rename_area.setObjectName("SecondaryButton")
        self.btn_rename_area.setMinimumHeight(28)
        btn_row.addWidget(self.btn_rename_area)
        
        self.btn_delete_area = QPushButton(" Elimina")
        self.btn_delete_area.setObjectName("SecondaryButton")
        self.btn_delete_area.setStyleSheet("color: #c0392b; font-weight: bold;")
        self.btn_delete_area.setMinimumHeight(28)
        btn_row.addWidget(self.btn_delete_area)
        
        mgt_layout.addLayout(btn_row)
        self.main_layout.addWidget(self.group_management)

        # 1. Activate Tool Card
        self.btn_activate_tool = QPushButton(" Attiva Strumento Modifica")
        self.btn_activate_tool.setCheckable(True)
        self.btn_activate_tool.setObjectName("SecondaryButton")
        self.btn_activate_tool.setMinimumHeight(38)
        self.main_layout.addWidget(self.btn_activate_tool)

        # Container for params (appears when tool is active)
        self.sub_area_params_widget = QWidget()
        params_layout = QVBoxLayout(self.sub_area_params_widget)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(0)
        
        # --- CARD 1: DIMENSIONI ---
        self.group_dimensions = QGroupBox("Dimensioni")
        self.group_dimensions.setObjectName("SubCard")
        dim_layout = QFormLayout(self.group_dimensions)
        dim_layout.setContentsMargins(10, 20, 10, 10)
        dim_layout.setLabelAlignment(Qt.AlignRight)
        
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(10, 1000000)
        self.spin_width.setDecimals(2)
        self.spin_width.setSuffix(" m")
        
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(10, 1000000)
        self.spin_height.setDecimals(2)
        self.spin_height.setSuffix(" m")
        
        self.spin_rotation = QDoubleSpinBox()
        self.spin_rotation.setRange(-360, 360)
        self.spin_rotation.setDecimals(2)
        self.spin_rotation.setSuffix(" °")
        
        dim_layout.addRow("Larghezza:", self.spin_width)
        dim_layout.addRow("Altezza:", self.spin_height)
        dim_layout.addRow("Rotazione:", self.spin_rotation)
        params_layout.addWidget(self.group_dimensions)
        
        # --- CARD 2: GRIGLIA & SIMULAZIONE ---
        self.group_grid = QGroupBox("Griglia & Simulazione")
        self.group_grid.setObjectName("SubCard")
        grid_layout = QVBoxLayout(self.group_grid)
        grid_layout.setContentsMargins(10, 20, 10, 10)
        grid_layout.setSpacing(8)
        
        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("Lato Griglia:"))
        self.spin_grid = QDoubleSpinBox()
        self.spin_grid.setRange(1, 1000)
        self.spin_grid.setDecimals(2)
        self.spin_grid.setSuffix(" m")
        grid_row.addWidget(self.spin_grid)
        grid_layout.addLayout(grid_row)
        
        # Element Count Badge
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        self.lbl_grid_stats = QLabel("- × - elements")
        self.lbl_grid_stats.setObjectName("BadgeText")
        badge_row.addWidget(self.lbl_grid_stats)
        grid_layout.addLayout(badge_row)
        
        self.chk_preview = QCheckBox("Anteprima Griglia su Mappa")
        grid_layout.addWidget(self.chk_preview)
        
        params_layout.addWidget(self.group_grid)
        
        # --- CARD 3: STRUMENTI SNAP ---
        self.group_snap = QGroupBox("Strumenti Snap")
        self.group_snap.setObjectName("SubCard")
        snap_v_layout = QVBoxLayout(self.group_snap)
        snap_v_layout.setContentsMargins(10, 20, 10, 10)
        snap_v_layout.setSpacing(8)
        
        self.chk_snap_internal = QCheckBox("Attiva Snap (Angoli/Centro)")
        self.chk_snap_internal.setChecked(True)
        snap_v_layout.addWidget(self.chk_snap_internal)
        
        snap_tol_row = QHBoxLayout()
        snap_tol_row.addWidget(QLabel("Tolleranza (px):"))
        self.spin_snap_tolerance = QSpinBox()
        self.spin_snap_tolerance.setRange(5, 200)
        self.spin_snap_tolerance.setValue(15)
        self.spin_snap_tolerance.setFixedWidth(65)
        snap_tol_row.addWidget(self.spin_snap_tolerance)
        snap_tol_row.addStretch()
        snap_v_layout.addLayout(snap_tol_row)
        
        params_layout.addWidget(self.group_snap)

        # --- CARD 4: CALCOLO DAVENPORT ROUGHNESS (3x3) ---
        self.group_davenport = QGroupBox("Calcolo Davenport Roughness (3x3)")
        self.group_davenport.setObjectName("SubCard")
        davenport_v_layout = QVBoxLayout(self.group_davenport)
        davenport_v_layout.setContentsMargins(10, 20, 10, 10)
        davenport_v_layout.setSpacing(8)

        self.btn_calc_davenport = QPushButton(" Calcola Roughness Dintorni")
        self.btn_calc_davenport.setObjectName("PrimaryButton")
        self.btn_calc_davenport.setMinimumHeight(30)
        davenport_v_layout.addWidget(self.btn_calc_davenport)

        # 3x3 Grid Display
        self.grid_davenport_layout = QGridLayout()
        self.grid_davenport_layout.setSpacing(4)
        self.davenport_labels = {}
        
        sectors = [
            ("NW", 0, 0), ("N", 0, 1), ("NE", 0, 2),
            ("W", 1, 0),  ("Center", 1, 1), ("E", 1, 2),
            ("SW", 2, 0), ("S", 2, 1), ("SE", 2, 2)
        ]
        for label, row, col in sectors:
            lbl = QLabel(f"<b>{label}</b><br/>-<br/><font color='#7f8c8d' size='1'>N/D</font>")
            lbl.setAlignment(Qt.AlignCenter)
            if label == "Center":
                lbl.setStyleSheet("border: 1px dashed #7f8c8d; border-radius: 4px; padding: 4px; background-color: #f1f2f6; min-height: 40px;")
            else:
                lbl.setStyleSheet("border: 1px solid #dfe4ea; border-radius: 4px; padding: 4px; background-color: #ffffff; min-height: 40px;")
            self.grid_davenport_layout.addWidget(lbl, row, col)
            self.davenport_labels[label] = lbl

        davenport_v_layout.addLayout(self.grid_davenport_layout)

        # Wind direction control
        wind_row = QHBoxLayout()
        wind_row.addWidget(QLabel("Direzione Vento Bordo (°):"))
        self.spin_wind_dir = QDoubleSpinBox()
        self.spin_wind_dir.setRange(0.0, 360.0)
        self.spin_wind_dir.setValue(247.50)
        self.spin_wind_dir.setDecimals(2)
        self.spin_wind_dir.setSuffix(" °")
        self.spin_wind_dir.setFixedWidth(90)
        wind_row.addWidget(self.spin_wind_dir)
        davenport_v_layout.addLayout(wind_row)

        # Recommended roughness label
        self.lbl_recommended_z0 = QLabel("Rugosità sopravento consigliata: -")
        self.lbl_recommended_z0.setStyleSheet("font-weight: bold; color: #2c3e50; padding: 5px;")
        self.lbl_recommended_z0.setWordWrap(True)
        davenport_v_layout.addWidget(self.lbl_recommended_z0)

        # Draw map layer button
        self.btn_draw_davenport_grid = QPushButton(" Disegna Griglia su Mappa")
        self.btn_draw_davenport_grid.setObjectName("SecondaryButton")
        self.btn_draw_davenport_grid.setMinimumHeight(28)
        self.btn_draw_davenport_grid.setEnabled(False)
        davenport_v_layout.addWidget(self.btn_draw_davenport_grid)

        params_layout.addWidget(self.group_davenport)
        
        # Reset Button (Discreet)
        self.btn_reset_sub_area = QPushButton(" Reset ad AOI")
        self.btn_reset_sub_area.setFlat(True)
        self.btn_reset_sub_area.setStyleSheet("font-size: 10px; color: #d35400; font-weight: bold;")
        
        reset_h_layout = QHBoxLayout()
        reset_h_layout.addStretch()
        reset_h_layout.addWidget(self.btn_reset_sub_area)
        reset_h_layout.addStretch()
        params_layout.addLayout(reset_h_layout)
        params_layout.addSpacing(10)

        # 2. Parameters Section - appears in the middle
        self.sub_area_params_widget.hide()
        self.main_layout.addWidget(self.sub_area_params_widget)
        
        # 3. Apply Button
        self.btn_apply_sub_area = QPushButton(" Applica e Genera Layer Area")
        self.btn_apply_sub_area.setObjectName("PrimaryButton")
        self.btn_apply_sub_area.setMinimumHeight(42)
        self.main_layout.addWidget(self.btn_apply_sub_area)

        # --- CARD 5: CORREZIONE ALLINEAMENTO RASTER (EnvyMap) ---
        self.group_fix_raster = QGroupBox("Correzione Allineamento Raster (EnvyMap)")
        self.group_fix_raster.setObjectName("SubCard")
        fix_raster_layout = QVBoxLayout(self.group_fix_raster)
        fix_raster_layout.setContentsMargins(10, 20, 10, 10)
        fix_raster_layout.setSpacing(8)
        
        # Row 1: Raster Layer selection
        raster_row = QHBoxLayout()
        raster_row.addWidget(QLabel("Raster Layer:"))
        self.combo_raster_layers = QgsCheckableComboBox()
        self.combo_raster_layers.setDefaultText("Seleziona uno o più raster...")
        self.combo_raster_layers.setMinimumHeight(28)
        raster_row.addWidget(self.combo_raster_layers)
        
        fix_raster_layout.addLayout(raster_row)
        
        # Row 2: Refresh + Select/Deselect All buttons
        sel_buttons_row = QHBoxLayout()
        
        self.btn_refresh_rasters = QPushButton("⟳ Aggiorna Lista")
        self.btn_refresh_rasters.setFlat(True)
        self.btn_refresh_rasters.setStyleSheet(
            "font-size: 11px; color: #27ae60; font-weight: bold; background: none; border: none; padding: 2px 5px;"
        )
        self.btn_refresh_rasters.setToolTip("Aggiorna la lista dei layer raster nel progetto")
        sel_buttons_row.addWidget(self.btn_refresh_rasters)
        
        sel_buttons_row.addStretch()
        
        self.btn_select_all_rasters = QPushButton("Seleziona Tutti")
        self.btn_select_all_rasters.setFlat(True)
        self.btn_select_all_rasters.setStyleSheet(
            "font-size: 11px; color: #0078d4; font-weight: bold; background: none; border: none; padding: 2px 5px;"
        )
        
        self.btn_deselect_all_rasters = QPushButton("Deseleziona Tutti")
        self.btn_deselect_all_rasters.setFlat(True)
        self.btn_deselect_all_rasters.setStyleSheet(
            "font-size: 11px; color: #d35400; font-weight: bold; background: none; border: none; padding: 2px 5px;"
        )
        
        sel_buttons_row.addWidget(self.btn_select_all_rasters)
        sel_buttons_row.addWidget(self.btn_deselect_all_rasters)
        fix_raster_layout.addLayout(sel_buttons_row)
        # Row 3: Resampling Algorithm
        resample_row = QHBoxLayout()
        resample_row.addWidget(QLabel("Campionamento:"))
        self.combo_resampling = QComboBox()
        self.combo_resampling.addItems([
            "Nearest Neighbor (Vicino più prossimo)",
            "Bilinear (Bilineare)",
            "Cubic (Cubico)"
        ])
        self.combo_resampling.setMinimumHeight(28)
        resample_row.addWidget(self.combo_resampling)
        fix_raster_layout.addLayout(resample_row)

        # Row 4: Run Fix Button
        self.btn_run_fix_raster = QPushButton(" Correggi Allineamento Raster")
        self.btn_run_fix_raster.setObjectName("PrimaryButton")
        self.btn_run_fix_raster.setMinimumHeight(35)
        fix_raster_layout.addWidget(self.btn_run_fix_raster)
        
        self.main_layout.addWidget(self.group_fix_raster)
        self.main_layout.addStretch()

        # Connections
        self.btn_activate_tool.toggled.connect(self._toggle_sub_area_tool)
        self.btn_apply_sub_area.clicked.connect(self._apply_sub_area_and_generate_layer)
        self.spin_width.valueChanged.connect(self._update_sub_area_params)
        self.spin_height.valueChanged.connect(self._update_sub_area_params)
        self.spin_rotation.valueChanged.connect(self._update_sub_area_params)
        self.spin_grid.valueChanged.connect(self._update_sub_area_params)
        self.chk_preview.toggled.connect(self._update_sub_area_params)
        self.chk_snap_internal.toggled.connect(self._update_sub_area_params)
        self.spin_snap_tolerance.valueChanged.connect(self._update_sub_area_params)
        self.btn_reset_sub_area.clicked.connect(self._reset_sub_area_to_aoi)
        
        # Davenport connections
        self.btn_calc_davenport.clicked.connect(self._calculate_davenport)
        self.spin_wind_dir.valueChanged.connect(self._update_davenport_ui)
        self.btn_draw_davenport_grid.clicked.connect(self._draw_davenport_grid)
        
        self.combo_sub_areas.currentTextChanged.connect(self._on_sub_area_changed)
        self.btn_new_area.clicked.connect(self._add_new_sub_area)
        self.btn_copy_area.clicked.connect(self._copy_sub_area)
        self.btn_rename_area.clicked.connect(self._rename_sub_area)
        self.btn_delete_area.clicked.connect(self._delete_sub_area)
        self.btn_color.colorChanged.connect(self._on_color_changed)
        
        # Fix raster connections
        self.btn_refresh_rasters.clicked.connect(self._refresh_raster_layers)
        self.btn_run_fix_raster.clicked.connect(self._run_raster_alignment_fix)
        self.btn_select_all_rasters.clicked.connect(self.combo_raster_layers.selectAllOptions)
        self.btn_deselect_all_rasters.clicked.connect(self.combo_raster_layers.deselectAllOptions)
        
        # Populate initial rasters
        self._refresh_raster_layers()

    def _get_dashboard(self):
        """Helper to navigate up to the EnviProtocolDashboard instance."""
        dashboard = self.parent()
        from ..dashboard import EnviProtocolDashboard
        p = dashboard
        while p and not isinstance(p, EnviProtocolDashboard):
            p = p.parent()
        return p

    def _toggle_sub_area_tool(self, active):
        dashboard = self._get_dashboard()
        if not dashboard: return

        if active:
            self.sub_area_params_widget.show()
            extent, crs = dashboard.setup_section.get_extent_and_crs()
            if not extent:
                QMessageBox.warning(self, "Attenzione", "Cattura l'estensione nel Passaggio 1 prima di modificare la Sub Area.")
                self.btn_activate_tool.setChecked(False)
                return
            
            name = self.combo_sub_areas.currentText() or "default"
            from qgis.PyQt.QtGui import QColor
            custom_color = None
            if name in self.sub_areas and self.sub_areas[name].get("color"):
                custom_color = QColor(self.sub_areas[name]["color"])
            self.sub_area_tool = SubAreaMapTool(
                dashboard.iface.mapCanvas(), extent, crs,
                initial_state=self.sub_area_state, name=name, color=custom_color
            )
            self.sub_area_tool.geometryChanged.connect(self._on_sub_area_geometry_changed)
            dashboard.iface.mapCanvas().setMapTool(self.sub_area_tool)
            
            # Init UI from tool state
            self.spin_width.blockSignals(True)
            self.spin_height.blockSignals(True)
            self.spin_rotation.blockSignals(True)
            self.spin_width.setValue(self.sub_area_tool.state.width)
            self.spin_height.setValue(self.sub_area_tool.state.height)
            self.spin_rotation.setValue(self.sub_area_tool.state.rotation)
            self.spin_width.blockSignals(False)
            self.spin_height.blockSignals(False)
            self.spin_rotation.blockSignals(False)
            
            self._update_sub_area_params()
        else:
            self.sub_area_params_widget.hide()
            dashboard.iface.mapCanvas().unsetMapTool(self.sub_area_tool)
            self.sub_area_tool = None
            self._remove_davenport_grid_layer()

    def _on_sub_area_geometry_changed(self, center, width, height, rotation):
        if not self.sub_area_tool: return
        self.sub_area_state = self.sub_area_tool.state
        
        self.spin_width.blockSignals(True)
        self.spin_height.blockSignals(True)
        self.spin_rotation.blockSignals(True)
        self.spin_width.setValue(width)
        self.spin_height.setValue(height)
        self.spin_rotation.setValue(rotation)
        self.spin_width.blockSignals(False)
        self.spin_height.blockSignals(False)
        self.spin_rotation.blockSignals(False)

        name = self.combo_sub_areas.currentText()
        if name and name in self.sub_areas:
            self.sub_areas[name]["center"] = center
            self.sub_areas[name]["width"] = width
            self.sub_areas[name]["height"] = height
            self.sub_areas[name]["rotation"] = rotation
            
        self._update_grid_badge()

    def _reset_sub_area_to_aoi(self):
        dashboard = self._get_dashboard()
        if not dashboard: return
        
        extent, crs = dashboard.setup_section.get_extent_and_crs()
        if not extent or extent.isEmpty():
            QMessageBox.warning(self, "Attenzione", "Cattura l'estensione nel Passaggio 1 prima di resettare.")
            return
            
        self.spin_width.blockSignals(True)
        self.spin_height.blockSignals(True)
        self.spin_rotation.blockSignals(True)
        self.spin_width.setValue(extent.width())
        self.spin_height.setValue(extent.height())
        self.spin_rotation.setValue(0.0)
        self.spin_width.blockSignals(False)
        self.spin_height.blockSignals(False)
        self.spin_rotation.blockSignals(False)
        
        if self.sub_area_tool:
            self.sub_area_tool.state.center = extent.center()
            self.sub_area_tool.state.width = extent.width()
            self.sub_area_tool.state.height = extent.height()
            self.sub_area_tool.state.rotation = 0.0
            self.sub_area_tool.update_geometry()
            self.sub_area_tool.canvas.refresh()
        
        if not self.sub_area_state:
            self.sub_area_state = SubAreaStatus()
        self.sub_area_state.center = extent.center()
        self.sub_area_state.width = extent.width()
        self.sub_area_state.height = extent.height()
        self.sub_area_state.rotation = 0.0

        name = self.combo_sub_areas.currentText()
        if name and name in self.sub_areas:
            self.sub_areas[name]["center"] = extent.center()
            self.sub_areas[name]["width"] = extent.width()
            self.sub_areas[name]["height"] = extent.height()
            self.sub_areas[name]["rotation"] = 0.0

    def _update_sub_area_params(self):
        name = self.combo_sub_areas.currentText()
        if name and name in self.sub_areas:
            self.sub_areas[name]["width"] = self.spin_width.value()
            self.sub_areas[name]["height"] = self.spin_height.value()
            self.sub_areas[name]["rotation"] = self.spin_rotation.value()
            self.sub_areas[name]["grid_size"] = self.spin_grid.value()
            
        if not self.sub_area_tool: return
        
        # Live calculation of grid elements for UX feedback
        w, h, g = self.spin_width.value(), self.spin_height.value(), self.spin_grid.value()
        self._update_grid_badge()
        
        success = self.sub_area_tool.set_params(
            w, h, self.spin_rotation.value(), g,
            self.chk_preview.isChecked(),
            self.chk_snap_internal.isChecked(),
            self.spin_snap_tolerance.value()
        )
        
        if not success:
            self.spin_width.blockSignals(True)
            self.spin_height.blockSignals(True)
            self.spin_rotation.blockSignals(True)
            self.spin_width.setValue(self.sub_area_tool.state.width)
            self.spin_height.setValue(self.sub_area_tool.state.height)
            self.spin_rotation.setValue(self.sub_area_tool.state.rotation)
            self.spin_width.blockSignals(False)
            self.spin_height.blockSignals(False)
            self.spin_rotation.blockSignals(False)

    def get_sub_area_geometry(self):
        if self.sub_area_tool:
            return self.sub_area_tool._get_geometry()
        if self.sub_area_state:
            return SubAreaMapTool.get_geometry_from_state(self.sub_area_state)
        return None

    def _apply_sub_area_and_generate_layer(self):
        dashboard = self._get_dashboard()
        if not dashboard: return

        extent, crs = dashboard.setup_section.get_extent_and_crs()
        if not extent:
            QMessageBox.warning(self, "Attenzione", "Cattura l'estensione nel Passaggio 1 prima di applicare.")
            return

        geom = self.get_sub_area_geometry()
        if not geom:
            QMessageBox.information(self, "Info", "Modifica i parametri o sposta l'area prima di applicare.")
            return

        from ...core.envimet_manager import ENVImetManager
        from ...core.constants import FolderNames, FileNames
        from qgis.core import QgsProject

        project = QgsProject.instance()
        project_path = project.fileName()
        if not project_path:
             QMessageBox.warning(self, "Errore", "Salva il progetto QGIS prima di procedere.")
             return

        project_dir = os.path.dirname(project_path)
        project_name = os.path.splitext(os.path.basename(project_path))[0]
        root_data_dir = os.path.join(project_dir, f"EnviProtocol+{project_name}")
        export_dir = os.path.join(root_data_dir, FolderNames.ENVIMET)

        if not os.path.exists(export_dir):
            os.makedirs(export_dir)

        sub_name = self.combo_sub_areas.currentText() or "default"
        if sub_name == "default":
            file_name = FileNames.EM_SUB_AREA
        else:
            file_name = f"sub_area_{sub_name}.gpkg"

        subarea_path = os.path.join(export_dir, file_name)
        crs_id = crs if isinstance(crs, str) else crs.authid()
        
        w = self.spin_width.value()
        h = self.spin_height.value()
        rot = self.spin_rotation.value()
        gs = self.spin_grid.value()
        
        # Edit-in-place is used in prepare_sub_area, so we do not remove the active layer from the project.

        custom_color = self.sub_areas.get(sub_name, {}).get("color", "")
        manager = ENVImetManager(dashboard.iface)
        ok, msg = manager.prepare_sub_area(
            extent, crs_id, subarea_path, geometry=geom,
            name=sub_name, width=w, height=h, rotation=rot, grid_size=gs,
            color=custom_color
        )

        if ok:
            # Update the internal state with final values
            centroid = geom.centroid().asPoint()
            self.sub_areas[sub_name] = {
                "center": centroid,
                "width": w,
                "height": h,
                "rotation": rot,
                "grid_size": gs,
                "color": custom_color,
                "file_path": subarea_path
            }
            
            # Automatically deactivate the tool and hide params on success
            self.btn_activate_tool.setChecked(False)
            
            # Delegate loading back to the dashboard/envimet_section if necessary, 
            # but for now we can call it if we have a reference.
            if hasattr(dashboard, "envimet_section"):
                dashboard.envimet_section._load_prepared_layers(file_name)
            QMessageBox.information(self, "Sub Area Generata", f"Il layer della Sub Area '{sub_name}' è stato creato/aggiornato con successo.")
        else:
            QMessageBox.critical(self, "Errore", f"Impossibile generare la Sub Area: {msg}")

    def showEvent(self, event):
        super().showEvent(event)
        self.load_sub_areas_from_disk()
        self._refresh_raster_layers()

    def _is_envimet_raster(self, name):
        """Helper to check if a raster layer name matches the ENVI-met naming pattern.
        
        Matches typical raw simulation outputs like:
        - Wind Speed_29.03._06.00.00_0.0m-3.0m_SeriesA
        - Air Temperature_29.03.2026_06.00.00_0.0m-3.0m_SeriesB
        - etc.
        Excludes already aligned/processed rasters containing '(Allineato)'.
        """
        if "(Allineato)" in name:
            return False
            
        # Standard ENVI-met naming parts
        has_date = bool(re.search(r'\d{2}\.\d{2}\.', name) or re.search(r'\d{4}-\d{2}-\d{2}', name))
        has_time = bool(re.search(r'\d{2}\.\d{2}\.\d{2}', name) or re.search(r'_\d{2}\.\d{2}_', name))
        has_series = "series" in name.lower()
        
        if (has_date and has_time) or (has_date and has_series) or (has_time and has_series):
            return True
            
        return False

    def _refresh_raster_layers(self):
        self.combo_raster_layers.blockSignals(True)
        
        # Save currently checked items to restore them
        previously_checked = []
        try:
            previously_checked = self.combo_raster_layers.checkedItems()
        except AttributeError:
            pass
            
        self.combo_raster_layers.clear()
        
        project = QgsProject.instance()
        rasters = []
        for lyr in project.mapLayers().values():
            if lyr.type() == Qgis.LayerType.RasterLayer:
                name = lyr.name()
                if self._is_envimet_raster(name):
                    rasters.append(name)
                
        if rasters:
            self.combo_raster_layers.setEnabled(True)
            self.combo_raster_layers.addItems(sorted(rasters))
            if previously_checked:
                # Restore only the items that are still in the new list
                to_check = [item for item in previously_checked if item in rasters]
                self.combo_raster_layers.setCheckedItems(to_check)
            self.btn_run_fix_raster.setEnabled(True)
            self.btn_select_all_rasters.setEnabled(True)
            self.btn_deselect_all_rasters.setEnabled(True)
        else:
            self.combo_raster_layers.addItem("Nessun layer raster trovato")
            self.combo_raster_layers.setEnabled(False)
            self.btn_run_fix_raster.setEnabled(False)
            self.btn_select_all_rasters.setEnabled(False)
            self.btn_deselect_all_rasters.setEnabled(False)
            
        self.combo_raster_layers.blockSignals(False)

    def _run_raster_alignment_fix(self):
        sub_name = self.get_active_sub_area_name()
        if not sub_name or sub_name not in self.sub_areas:
            QMessageBox.warning(self, "Attenzione", "Seleziona una Sub Area valida con dimensioni/rotazione salvate.")
            return

        sub_info = self.sub_areas[sub_name]
        
        # Determine selected raster layers
        selected_lyr_names = []
        try:
            selected_lyr_names = self.combo_raster_layers.checkedItems()
        except AttributeError:
            cur_text = self.combo_raster_layers.currentText()
            if cur_text and cur_text != "Nessun layer raster trovato":
                selected_lyr_names = [cur_text]
                
        if not selected_lyr_names:
            QMessageBox.warning(self, "Attenzione", "Seleziona almeno un raster layer da allineare.")
            return

        # Determine target CRS from subarea or project
        target_crs_auth = None
        subarea_path = sub_info.get("file_path")
        if subarea_path and os.path.exists(subarea_path):
            temp_lyr = QgsVectorLayer(subarea_path, "temp_sub", "ogr")
            if temp_lyr.isValid():
                target_crs_auth = temp_lyr.crs().authid()
                
        if not target_crs_auth:
            target_crs_auth = QgsProject.instance().crs().authid()

        # Determine destination folder (inside project's data directory)
        project = QgsProject.instance()
        project_path = project.fileName()
        if not project_path:
            QMessageBox.warning(self, "Errore", "Salva il progetto QGIS prima di procedere.")
            return

        project_dir = os.path.dirname(project_path)
        project_name = os.path.splitext(os.path.basename(project_path))[0]
        root_data_dir = os.path.join(project_dir, f"EnviProtocol+{project_name}")
        fixed_dir = os.path.join(root_data_dir, "Risultati_Allineati")
        if not os.path.exists(fixed_dir):
            try:
                os.makedirs(fixed_dir)
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile creare la cartella per i raster allineati: {str(e)}")
                return

        # Get params
        center = sub_info["center"]
        width = sub_info["width"]
        height = sub_info["height"]
        rotation = sub_info["rotation"]
        
        # Get resampling method
        resample_idx = self.combo_resampling.currentIndex()
        resamp_methods = ["nearest", "bilinear", "cubic"]
        resample_str = resamp_methods[resample_idx] if resample_idx < len(resamp_methods) else "nearest"

        from ...core.envimet_manager import ENVImetManager
        dashboard = self._get_dashboard()
        manager = ENVImetManager(dashboard.iface if dashboard else None)
        
        success_list = []
        failure_list = []
        total = len(selected_lyr_names)

        for idx, lyr_name in enumerate(selected_lyr_names):
            if lyr_name == "Nessun layer raster trovato":
                continue
                
            # Find source raster path and keep reference for later removal
            src_path = ""
            src_layer = None
            for lyr in project.mapLayers().values():
                if lyr.name() == lyr_name and lyr.type() == Qgis.LayerType.RasterLayer:
                    src_path = lyr.source()
                    src_layer = lyr
                    break
                    
            if not src_path or not os.path.exists(src_path):
                failure_list.append(f"{lyr_name}: Percorso sorgente non valido o non esistente.")
                continue

            # Update progress UI
            if dashboard and hasattr(dashboard, "progress_section"):
                dashboard.progress_section.set_status(
                    f"Allineamento raster {lyr_name} in corso ({idx + 1} di {total})...", 
                    is_busy=True
                )
            QgsApplication.processEvents()

            # Use sanitized QGIS layer name to ensure unique filenames for different variables (e.g. NetCDF)
            # Include sub_name prefix so that different sub-areas don't overwrite each other's files
            base_name = re.sub(r'[\\/*?:"<>|]', '_', lyr_name)
            dest_path = os.path.join(fixed_dir, f"{sub_name}_{base_name}.tif")

            # Remove existing layer if loaded in QGIS to unlock the file
            existing_lyr = None
            for lyr in project.mapLayers().values():
                if lyr.source() == dest_path:
                    existing_lyr = lyr
                    break
                    
            if existing_lyr:
                project.removeMapLayer(existing_lyr)

            # Run fix
            ok, msg = manager.fix_envymap_raster_alignment(
                src_path=src_path,
                dest_path=dest_path,
                center_x=center.x(),
                center_y=center.y(),
                width=width,
                height=height,
                rotation_deg=rotation,
                target_crs_auth=target_crs_auth,
                resampling_method=resample_str
            )

            if ok:
                # Add to project in a custom group
                out_lyr_name = f"{sub_name}_{base_name} (Allineato)"
                new_layer = QgsRasterLayer(dest_path, out_lyr_name)
                if new_layer.isValid():
                    # Apply ENVI-met color palette based on variable name
                    try:
                        from ...core.raster_palettes import apply_envimet_palette
                        apply_envimet_palette(new_layer, lyr_name)
                    except Exception as palette_err:
                        QgsMessageLog.logMessage(
                            f"Errore applicazione palette per {lyr_name}: {palette_err}",
                            "EnviProtocol", Qgis.Warning
                        )
                    
                    root = project.layerTreeRoot()
                    # Find existing group safely at the root level to avoid duplicates
                    group = None
                    for child in root.children():
                        if child.nodeType() == 0 and child.name() == "Risultati Allineati (EnvyMap)":
                            group = child
                            break
                    if not group:
                        # Insert at the top of the layer tree
                        group = root.insertGroup(0, "Risultati Allineati (EnvyMap)")
                    project.addMapLayer(new_layer, False)
                    group.addLayer(new_layer)
                success_list.append(lyr_name)

                # Remove old source layer from project and delete temp file from disk
                if src_layer:
                    layer_id = src_layer.id()
                    project.removeMapLayer(layer_id)
                    import tempfile
                    temp_dir = os.path.normpath(tempfile.gettempdir())
                    if src_path and os.path.normpath(src_path).startswith(temp_dir):
                        try:
                            os.remove(src_path)
                        except Exception:
                            pass
            else:
                failure_list.append(f"{lyr_name}: {msg}")

        # Reset progress bar
        if dashboard and hasattr(dashboard, "progress_section"):
            dashboard.progress_section.reset()

        # Refresh list of rasters to include the new ones
        self._refresh_raster_layers()

        # Display final result dialogs
        if not failure_list:
            QMessageBox.information(
                self, "Successo", 
                f"Tutti i raster selezionati ({len(success_list)}) sono stati allineati correttamente e aggiunti al gruppo 'Risultati Allineati (EnvyMap)'."
            )
        elif not success_list:
            QMessageBox.critical(
                self, "Errore di Allineamento", 
                "Nessuno dei raster selezionati è stato allineato correttamente.\n\nErrori:\n" + "\n".join(failure_list)
            )
        else:
            QMessageBox.warning(
                self, "Allineamento Completato con Errori", 
                f"L'operazione è stata completata con alcuni errori.\n\n"
                f"Successi ({len(success_list)}):\n" + "\n".join(f"- {s}" for s in success_list) + "\n\n"
                f"Fallimenti ({len(failure_list)}):\n" + "\n".join(f"- {f}" for f in failure_list)
            )

    def _get_export_dir(self):
        dashboard = self._get_dashboard()
        if not dashboard: return None
        project = QgsProject.instance()
        project_path = project.fileName()
        if not project_path: return None
        project_dir = os.path.dirname(project_path)
        project_name = os.path.splitext(os.path.basename(project_path))[0]
        from ...core.constants import FolderNames
        return os.path.join(project_dir, f"EnviProtocol+{project_name}", FolderNames.ENVIMET)

    def get_active_sub_area_name(self):
        return self.combo_sub_areas.currentText() or "default"
        
    def get_active_sub_area_params(self):
        name = self.get_active_sub_area_name()
        if name in self.sub_areas:
            return self.sub_areas[name]
        return None

    def _update_combo_box_items(self, selected_name=None):
        self.combo_sub_areas.blockSignals(True)
        self.combo_sub_areas.clear()
        if self.sub_areas:
            self.combo_sub_areas.addItems(sorted(self.sub_areas.keys()))
        if selected_name:
            idx = self.combo_sub_areas.findText(selected_name)
            if idx != -1:
                self.combo_sub_areas.setCurrentIndex(idx)
            elif self.combo_sub_areas.count() > 0:
                self.combo_sub_areas.setCurrentIndex(0)
        elif self.combo_sub_areas.count() > 0:
            self.combo_sub_areas.setCurrentIndex(0)
        self.combo_sub_areas.blockSignals(False)

    def load_sub_areas_from_disk(self):
        """Scans the export directory and QGIS layers for sub_area GPKG files and populates the internal list."""
        export_dir = self._get_export_dir()
        
        current_selection = self.combo_sub_areas.currentText()
        self.sub_areas.clear()
        
        file_paths_to_process = set()
        
        # 1. Scan export directory
        if export_dir and os.path.exists(export_dir):
            for filename in os.listdir(export_dir):
                if filename.startswith("sub_area") and filename.endswith(".gpkg"):
                    file_paths_to_process.add(os.path.join(export_dir, filename))
                    
        # 2. Scan QGIS layer tree
        project = QgsProject.instance()
        for lyr in project.mapLayers().values():
            if lyr.type() == Qgis.LayerType.VectorLayer:
                source = lyr.source()
                # Use custom property if available, otherwise check layer name
                fetch_name = lyr.customProperty("fetch_filename")
                lname = lyr.name()
                
                is_sub_area = False
                if fetch_name and isinstance(fetch_name, str) and fetch_name.startswith("sub_area") and fetch_name.endswith(".gpkg"):
                    is_sub_area = True
                elif lname.startswith("Sub Area") and lname.endswith("(ENVI-met)"):
                    is_sub_area = True
                elif source and "sub_area" in os.path.basename(source) and source.endswith(".gpkg"):
                    is_sub_area = True
                    
                if is_sub_area and source:
                    clean_source = source.split("|")[0] if "|" in source else source
                    if os.path.exists(clean_source):
                        file_paths_to_process.add(clean_source)
        
        if not file_paths_to_process:
            self.combo_sub_areas.blockSignals(True)
            self.combo_sub_areas.clear()
            self.combo_sub_areas.blockSignals(False)
            self._on_sub_area_changed()
            return
            
        for file_path in file_paths_to_process:
            filename = os.path.basename(file_path)
            if filename == "sub_area.gpkg":
                name = "default"
            elif filename.startswith("sub_area_") and filename.endswith(".gpkg"):
                name = filename[len("sub_area_"):-len(".gpkg")]
            else:
                name = "default"
            
            layer = QgsVectorLayer(file_path, "temp_sub", "ogr")
            if layer.isValid() and layer.featureCount() > 0:
                features = list(layer.getFeatures())
                if features:
                    feat = features[0]
                    geom = feat.geometry()
                    if geom.isEmpty(): continue
                    
                    center = geom.centroid().asPoint()
                    
                    width = feat.attribute("width") if layer.fields().indexFromName("width") != -1 else None
                    height = feat.attribute("height") if layer.fields().indexFromName("height") != -1 else None
                    rotation = feat.attribute("rotation") if layer.fields().indexFromName("rotation") != -1 else None
                    grid_size = feat.attribute("grid_size") if layer.fields().indexFromName("grid_size") != -1 else None
                    color = feat.attribute("color") if layer.fields().indexFromName("color") != -1 else None
                    
                    from qgis.PyQt.QtCore import QVariant
                    if isinstance(width, QVariant) or width is None: width = 100.0
                    if isinstance(height, QVariant) or height is None: height = 100.0
                    if isinstance(rotation, QVariant) or rotation is None: rotation = 0.0
                    if isinstance(grid_size, QVariant) or grid_size is None: grid_size = 2.0
                    if isinstance(color, QVariant) or color is None:
                        color = ""
                    else:
                        color = str(color).strip()
                    
                    try:
                        width = float(width)
                        height = float(height)
                        rotation = float(rotation)
                        grid_size = float(grid_size)
                    except:
                        width, height, rotation, grid_size = 100.0, 100.0, 0.0, 2.0
                        
                    # If fallback name, try to extract from layer feature's "name" attribute
                    if name == "default" and filename != "sub_area.gpkg":
                        if layer.fields().indexFromName("name") != -1:
                            attr_name = feat.attribute("name")
                            if attr_name and not isinstance(attr_name, QVariant):
                                name = str(attr_name)
                        
                    self.sub_areas[name] = {
                        "center": center,
                        "width": width,
                        "height": height,
                        "rotation": rotation,
                        "grid_size": grid_size,
                        "color": color,
                        "file_path": file_path
                    }
        
        self._update_combo_box_items(current_selection)
        self._on_sub_area_changed()

    def _on_sub_area_changed(self):
        self._remove_davenport_grid_layer()
        self.davenport_results = None
        if hasattr(self, 'btn_draw_davenport_grid') and self.btn_draw_davenport_grid:
            self.btn_draw_davenport_grid.setEnabled(False)
        if hasattr(self, 'davenport_labels') and self.davenport_labels:
            for label, lbl in self.davenport_labels.items():
                if label == "Center":
                    lbl.setStyleSheet("border: 1px dashed #7f8c8d; border-radius: 4px; padding: 4px; background-color: #f1f2f6; min-height: 40px;")
                else:
                    lbl.setStyleSheet("border: 1px solid #dfe4ea; border-radius: 4px; padding: 4px; background-color: #ffffff; min-height: 40px;")
                lbl.setText(f"<b>{label}</b><br/>-<br/><font color='#7f8c8d' size='1'>N/D</font>")
        if hasattr(self, 'lbl_recommended_z0') and self.lbl_recommended_z0:
            self.lbl_recommended_z0.setText("Rugosità sopravento consigliata: -")

        name = self.combo_sub_areas.currentText()
        has_area = bool(name and name in self.sub_areas)
        
        self.combo_sub_areas.setEnabled(has_area)
        self.btn_color.setEnabled(has_area)
        self.btn_copy_area.setEnabled(has_area)
        self.btn_rename_area.setEnabled(has_area)
        self.btn_delete_area.setEnabled(has_area)
        self.btn_activate_tool.setEnabled(has_area)
        self.btn_apply_sub_area.setEnabled(has_area)
        
        if not has_area:
            self.sub_area_state = None
            if self.btn_activate_tool.isChecked():
                self.btn_activate_tool.setChecked(False)
            return
        
        item = self.sub_areas[name]
        
        self.spin_width.blockSignals(True)
        self.spin_height.blockSignals(True)
        self.spin_rotation.blockSignals(True)
        self.spin_grid.blockSignals(True)
        
        self.spin_width.setValue(item["width"])
        self.spin_height.setValue(item["height"])
        self.spin_rotation.setValue(item["rotation"])
        self.spin_grid.setValue(item["grid_size"])
        
        self.spin_width.blockSignals(False)
        self.spin_height.blockSignals(False)
        self.spin_rotation.blockSignals(False)
        self.spin_grid.blockSignals(False)
        
        if not self.sub_area_state:
            self.sub_area_state = SubAreaStatus()
            
        self.sub_area_state.center = item["center"]
        self.sub_area_state.width = item["width"]
        self.sub_area_state.height = item["height"]
        self.sub_area_state.rotation = item["rotation"]
        
        # Update the QgsColorButton color
        from ...core.utils import get_color_for_sub_area
        from qgis.PyQt.QtGui import QColor
        custom_color_str = item.get("color", "")
        if custom_color_str:
            current_color = QColor(custom_color_str)
        else:
            current_color = get_color_for_sub_area(name)
            
        self.btn_color.blockSignals(True)
        self.btn_color.setColor(current_color)
        self.btn_color.blockSignals(False)

        if self.sub_area_tool:
            self.sub_area_tool.update_colors(name)
            if custom_color_str:
                self.sub_area_tool.update_colors_from_color(current_color)
            self.sub_area_tool.state = self.sub_area_state
            self.sub_area_tool.grid_size = item["grid_size"]
            self.sub_area_tool.update_geometry(force_grid=True)
            self.sub_area_tool.canvas.refresh()
            
        self._update_grid_badge()

        # ZOOM AND ACTIVATE THE ACTIVE SUB-AREA (keeping original aesthetics intact)
        dashboard = self._get_dashboard()
        if dashboard:
            # Find the active layer matching the selected sub-area
            target_layer = None
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.source() == item.get("file_path"):
                    target_layer = lyr
                    break

            # Activate the layer in QGIS legend without selection highlighting
            if target_layer:
                dashboard.iface.setActiveLayer(target_layer)

            # Zoom canvas to the sub-area geometry
            state = SubAreaStatus(item["center"], item["width"], item["height"], item["rotation"])
            geom = SubAreaMapTool.get_geometry_from_state(state)
            if geom and not geom.isEmpty():
                extent = geom.boundingBox()
                if extent and not extent.isEmpty():
                    extent.scale(1.2)  # Add 20% margin
                    canvas = dashboard.iface.mapCanvas()
                    
                    # Coordinate transform if layer CRS is different from canvas CRS
                    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
                    
                    # Try to get the source CRS of the sub-area layer
                    src_crs = None
                    if target_layer:
                        src_crs = target_layer.crs()
                    elif item.get("file_path") and os.path.exists(item["file_path"]):
                        temp_layer = QgsVectorLayer(item["file_path"], "temp_zoom_crs", "ogr")
                        if temp_layer.isValid():
                            src_crs = temp_layer.crs()
                            
                    # Fallback to the project CRS if still not found
                    if not src_crs or not src_crs.isValid():
                        src_crs = QgsProject.instance().crs()
                        
                    dest_crs = canvas.mapSettings().destinationCrs()
                    if src_crs.isValid() and dest_crs.isValid() and src_crs != dest_crs:
                        transform = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())
                        try:
                            extent = transform.transformBoundingBox(extent)
                        except Exception as e:
                            from qgis.core import QgsMessageLog, Qgis
                            QgsMessageLog.logMessage(f"Failed to transform extent for zoom: {e}", "EnviProtocol", Qgis.Warning)
                            
                    canvas.setExtent(extent)
                    canvas.refresh()

    def _on_color_changed(self, color):
        name = self.combo_sub_areas.currentText()
        if not name or name not in self.sub_areas: return
        
        hex_color = color.name()
        self.sub_areas[name]["color"] = hex_color
        
        # 1. Update the active tool's rubber bands immediately
        if self.sub_area_tool:
            self.sub_area_tool.update_colors_from_color(color)
            self.sub_area_tool.canvas.refresh()
            
        # 2. Update the styled layer in the map legend immediately if loaded
        from ...core.constants import FileNames
        project = QgsProject.instance()
        export_dir = self._get_export_dir()
        if export_dir:
            file_name = FileNames.EM_SUB_AREA if name == "default" else f"sub_area_{name}.gpkg"
            subarea_path = os.path.join(export_dir, file_name)
            for layer in project.mapLayers().values():
                if layer.source() == subarea_path:
                    # Apply styling immediately
                    dashboard = self._get_dashboard()
                    if dashboard and hasattr(dashboard, "envimet_section"):
                        dashboard.envimet_section._apply_sub_area_styling(layer)
                    break

    def _update_grid_badge(self):
        w = self.spin_width.value()
        h = self.spin_height.value()
        g = self.spin_grid.value()
        if g > 0:
            nx, ny = int(w / g), int(h / g)
            total = nx * ny
            self.lbl_grid_stats.setText(f"{nx} × {ny} ➜ {total:,} elementi".replace(",", "."))

    def _add_new_sub_area(self):
        dashboard = self._get_dashboard()
        if not dashboard: return
        
        extent, crs = dashboard.setup_section.get_extent_and_crs()
        if not extent or extent.isEmpty():
            QMessageBox.warning(self, "Attenzione", "Cattura l'estensione nel Passaggio 1 prima di creare una nuova area.")
            return
            
        name, ok = QInputDialog.getText(self, "Nuova Sub Area", "Inserisci il nome della nuova area:")
        if not ok or not name.strip():
            return
            
        import re
        sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', name.strip())
        if not sanitized_name:
            QMessageBox.warning(self, "Errore", "Nome non valido. Usa solo lettere, numeri e underscore.")
            return
            
        if sanitized_name in self.sub_areas:
            QMessageBox.warning(self, "Errore", f"L'area '{sanitized_name}' esiste già.")
            return
            
        export_dir = self._get_export_dir()
        if not export_dir:
            QMessageBox.warning(self, "Errore", "Salva il progetto QGIS prima di procedere.")
            return
            
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        file_name = f"sub_area_{sanitized_name}.gpkg"
        file_path = os.path.join(export_dir, file_name)
        
        w = extent.width() * 0.8
        h = extent.height() * 0.8
        rot = 0.0
        gs = 2.0
        center = extent.center()
        
        from ..widgets.sub_area_tool import SubAreaStatus, SubAreaMapTool
        state = SubAreaStatus(center, w, h, rot)
        geom = SubAreaMapTool.get_geometry_from_state(state)
        
        from ...core.envimet_manager import ENVImetManager
        crs_id = crs if isinstance(crs, str) else crs.authid()
        manager = ENVImetManager(dashboard.iface)
        
        ok, msg = manager.prepare_sub_area(
            extent, crs_id, file_path, geometry=geom,
            name=sanitized_name, width=w, height=h, rotation=rot, grid_size=gs,
            color=""
        )
        
        if not ok:
            QMessageBox.critical(self, "Errore", f"Impossibile generare la Sub Area: {msg}")
            return
        
        self.sub_areas[sanitized_name] = {
            "center": center,
            "width": w,
            "height": h,
            "rotation": rot,
            "grid_size": gs,
            "color": "",
            "file_path": file_path
        }
        
        if hasattr(dashboard, "envimet_section"):
            dashboard.envimet_section._load_prepared_layers(file_name)
            
        self._update_combo_box_items(sanitized_name)
        self._on_sub_area_changed()
        
        if self.sub_area_tool:
            self.sub_area_tool.state.center = center
            self.sub_area_tool.state.width = w
            self.sub_area_tool.state.height = h
            self.sub_area_tool.state.rotation = rot
            self.sub_area_tool.update_geometry(force_grid=True)
            self.sub_area_tool.canvas.refresh()

    def _safe_delete_file(self, path):
        """Safely attempts to remove a file on disk, logging a warning if it remains locked."""
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(f"Impossibile rimuovere il file bloccato {path}: {e}", "EnviProtocol", Qgis.Warning)

    def _rename_sub_area(self):
        name = self.combo_sub_areas.currentText()
        if not name or name not in self.sub_areas: return
        
        new_name, ok = QInputDialog.getText(self, "Rinomina Sub Area", f"Inserisci il nuovo nome per '{name}':", text=name)
        if not ok or not new_name.strip() or new_name.strip() == name:
            return
            
        import re
        sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', new_name.strip())
        if not sanitized_name:
            QMessageBox.warning(self, "Errore", "Nome non valido. Usa solo lettere, numeri e underscore.")
            return
            
        if sanitized_name in self.sub_areas:
            QMessageBox.warning(self, "Errore", f"L'area '{sanitized_name}' esiste già.")
            return
            
        item = self.sub_areas.pop(name)
        old_path = item["file_path"]
        export_dir = self._get_export_dir()
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir)
        new_file_name = f"sub_area_{sanitized_name}.gpkg"
        new_path = os.path.join(export_dir, new_file_name) if export_dir else ""
        
        if old_path and os.path.exists(old_path):
            try:
                import shutil
                # 1. Copy the GPKG file first (reading locked files is allowed on Windows)
                shutil.copy(old_path, new_path)
                
                # 2. Update the name attribute inside the newly copied GPKG file (not locked yet)
                from qgis.core import QgsVectorLayer
                temp_layer = QgsVectorLayer(new_path, "temp_update", "ogr")
                if temp_layer.isValid():
                    temp_layer.startEditing()
                    idx_name = temp_layer.fields().indexFromName("name")
                    if idx_name != -1:
                        for feat in temp_layer.getFeatures():
                            temp_layer.changeAttributeValue(feat.id(), idx_name, sanitized_name)
                    temp_layer.commitChanges()
                del temp_layer
                
                # 3. Redirect existing layers in QGIS project to new path to release the lock on old path
                project = QgsProject.instance()
                for lyr in list(project.mapLayers().values()):
                    if lyr.source() == old_path:
                        lyr.setDataSource(new_path, lyr.name().replace(name, sanitized_name), "ogr")
                        lyr.setName(lyr.name().replace(name, sanitized_name))
                        lyr.setCustomProperty("fetch_filename", f"sub_area_{sanitized_name}.gpkg")
                        
                        # Apply styling to ensure labeling is refreshed/configured correctly
                        dashboard = self._get_dashboard()
                        if dashboard and hasattr(dashboard, "envimet_section"):
                            dashboard.envimet_section._apply_sub_area_styling(lyr)
                            
                        lyr.triggerRepaint()
                
                # 4. Clean up Python references and trigger GC
                import gc
                gc.collect()
                
                # 5. Attempt to remove the old file, fallback to deferred removal if still locked
                try:
                    os.remove(old_path)
                except Exception:
                    from qgis.PyQt.QtCore import QTimer
                    QTimer.singleShot(1000, lambda: self._safe_delete_file(old_path))
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Impossibile rinominare il file: {e}")
                self.sub_areas[name] = item
                return
                
        item["file_path"] = new_path
        self.sub_areas[sanitized_name] = item
        
        self._update_combo_box_items(sanitized_name)
        self._on_sub_area_changed()

    def _delete_sub_area(self):
        name = self.combo_sub_areas.currentText()
        if not name or name not in self.sub_areas: return
        
        reply = QMessageBox.question(
            self, "Conferma eliminazione",
            f"Sei sicuro di voler eliminare la Sub Area '{name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
            
        item = self.sub_areas.pop(name)
        file_path = item["file_path"]
        if file_path and os.path.exists(file_path):
            try:
                project = QgsProject.instance()
                for lyr in list(project.mapLayers().values()):
                    if lyr.source() == file_path:
                        project.removeMapLayers([lyr.id()])
                
                import gc
                gc.collect()
                
                try:
                    os.remove(file_path)
                except Exception:
                    from qgis.PyQt.QtCore import QTimer
                    QTimer.singleShot(1000, lambda: self._safe_delete_file(file_path))
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Impossibile eliminare il file: {e}")
                
        idx = self.combo_sub_areas.currentIndex()
        self.combo_sub_areas.removeItem(idx)
        
        if self.combo_sub_areas.count() == 0:
            self.load_sub_areas_from_disk()

    def _copy_sub_area(self):
        current_name = self.combo_sub_areas.currentText()
        if not current_name or current_name not in self.sub_areas:
            return
            
        dashboard = self._get_dashboard()
        if not dashboard:
            return
            
        default_new_name = f"{current_name}_copy"
        new_name, ok = QInputDialog.getText(
            self, "Copia Sub Area",
            f"Inserisci il nome per la copia di '{current_name}':",
            text=default_new_name
        )
        if not ok or not new_name.strip():
            return
            
        import re
        sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', new_name.strip())
        if not sanitized_name:
            QMessageBox.warning(self, "Errore", "Nome non valido. Usa solo lettere, numeri e underscore.")
            return
            
        if sanitized_name in self.sub_areas:
            QMessageBox.warning(self, "Errore", f"L'area '{sanitized_name}' esiste già.")
            return
            
        export_dir = self._get_export_dir()
        if not export_dir:
            QMessageBox.warning(self, "Errore", "Salva il progetto QGIS prima di procedere.")
            return
            
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        new_file_name = f"sub_area_{sanitized_name}.gpkg"
        new_path = os.path.join(export_dir, new_file_name)
        
        current_item = self.sub_areas[current_name]
        old_path = current_item.get("file_path", "")
        
        self.sub_areas[sanitized_name] = {
            "center": current_item["center"],
            "width": current_item["width"],
            "height": current_item["height"],
            "rotation": current_item["rotation"],
            "grid_size": current_item["grid_size"],
            "color": current_item["color"],
            "file_path": new_path
        }
        
        if old_path and os.path.exists(old_path):
            try:
                import shutil
                shutil.copy(old_path, new_path)
                
                # Update the name attribute inside the newly copied GPKG file
                layer = QgsVectorLayer(new_path, "temp_update", "ogr")
                if layer.isValid():
                    layer.startEditing()
                    idx_name = layer.fields().indexFromName("name")
                    if idx_name != -1:
                        for feat in layer.getFeatures():
                            layer.changeAttributeValue(feat.id(), idx_name, sanitized_name)
                    layer.commitChanges()
                del layer
                import gc
                gc.collect()
            except Exception as e:
                self.sub_areas.pop(sanitized_name, None)
                QMessageBox.warning(self, "Errore", f"Impossibile copiare il file sul disco: {e}")
                return
                
        self._update_combo_box_items(sanitized_name)
        self._on_sub_area_changed()
        
        if old_path and os.path.exists(old_path):
            if hasattr(dashboard, "envimet_section"):
                dashboard.envimet_section._load_prepared_layers(new_file_name)
                
        QMessageBox.information(
            self, "Sub Area Copiata",
            f"La Sub Area '{current_name}' è stata copiata come '{sanitized_name}' con successo."
        )

    def _remove_davenport_grid_layer(self):
        project = QgsProject.instance()
        existing_layers = project.mapLayersByName("Griglia Davenport 3x3")
        if existing_layers:
            for lyr in existing_layers:
                project.removeMapLayer(lyr.id())
        if hasattr(self, 'btn_draw_davenport_grid') and self.btn_draw_davenport_grid:
            self.btn_draw_davenport_grid.setText(" Disegna Griglia su Mappa")

    def _calculate_davenport(self):
        dashboard = self._get_dashboard()
        if not dashboard: return
        
        self._remove_davenport_grid_layer()
        
        sub_name = self.get_active_sub_area_name()
        if not sub_name or sub_name not in self.sub_areas:
            QMessageBox.warning(self, "Attenzione", "Nessuna sub-area attiva selezionata.")
            return

        item = self.sub_areas[sub_name]
        
        project = QgsProject.instance()
        project_path = project.fileName()
        if not project_path:
            QMessageBox.warning(self, "Attenzione", "Salva il progetto QGIS prima di eseguire il calcolo.")
            return
        
        project_dir = os.path.dirname(project_path)
        
        if self.sub_area_tool:
            center = self.sub_area_tool.state.center
            width = self.spin_width.value()
            height = self.spin_height.value()
            rotation = self.spin_rotation.value()
        else:
            center = item["center"]
            width = item["width"]
            height = item["height"]
            rotation = item["rotation"]

        try:
            from ...core.envimet_manager import ENVImetManager
            from qgis.core import Qgis
            
            manager = ENVImetManager(dashboard.iface)
            
            dashboard.iface.messageBar().pushMessage("Calcolo Roughness", "Calcolo della roughness aerodinamica Davenport in corso...", level=Qgis.Info, duration=3)
            
            results = manager.calculate_davenport_roughness(
                project_dir, center.x(), center.y(), width, height, rotation
            )
            
            self.davenport_results = results
            self.btn_draw_davenport_grid.setEnabled(True)
            self._update_davenport_ui()
            
            dashboard.iface.messageBar().pushMessage("Calcolo Completato", "Roughness calcolata con successo.", level=Qgis.Success, duration=3)
            
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante il calcolo della roughness: {str(e)}")

    def _update_davenport_ui(self):
        if not hasattr(self, 'davenport_results') or not self.davenport_results:
            return
            
        wind_dir = self.spin_wind_dir.value()
        deg = wind_dir % 360
        if deg >= 337.5 or deg < 22.5:
            upwind_sector = "N"
        elif 22.5 <= deg < 67.5:
            upwind_sector = "NE"
        elif 67.5 <= deg < 112.5:
            upwind_sector = "E"
        elif 112.5 <= deg < 157.5:
            upwind_sector = "SE"
        elif 157.5 <= deg < 202.5:
            upwind_sector = "S"
        elif 202.5 <= deg < 247.5:
            upwind_sector = "SW"
        elif 247.5 <= deg < 292.5:
            upwind_sector = "W"
        else:
            upwind_sector = "NW"
            
        for label, lbl in self.davenport_labels.items():
            if label not in self.davenport_results: continue
            data = self.davenport_results[label]
            z0 = data['z0']
            cls = data['davenport_class']
            
            cls_display = cls.split('. ')[1] if '. ' in cls else cls
            txt = f"<b>{label}</b><br/>{z0:.4f} m<br/><font color='#7f8c8d' size='1'>{cls_display}</font>"
            lbl.setText(txt)
            
            if label == upwind_sector:
                lbl.setStyleSheet("border: 2px solid #2980b9; border-radius: 4px; padding: 4px; background-color: #e3f2fd; min-height: 40px; font-weight: bold;")
            elif label == "Center":
                lbl.setStyleSheet("border: 1px dashed #7f8c8d; border-radius: 4px; padding: 4px; background-color: #f1f2f6; min-height: 40px;")
            else:
                lbl.setStyleSheet("border: 1px solid #dfe4ea; border-radius: 4px; padding: 4px; background-color: #ffffff; min-height: 40px;")

        if upwind_sector in self.davenport_results:
            up_data = self.davenport_results[upwind_sector]
            z0_val = up_data['z0']
            cls_name = up_data['davenport_class']
            self.lbl_recommended_z0.setText(f"Rugosità sopravento consigliata ({upwind_sector}): <b>{z0_val:.4f} m</b><br/><font color='#7f8c8d'>({cls_name})</font>")
        else:
            self.lbl_recommended_z0.setText("Rugosità sopravento consigliata: -")

    def _draw_davenport_grid(self):
        project = QgsProject.instance()
        existing_layers = project.mapLayersByName("Griglia Davenport 3x3")
        if existing_layers:
            self._remove_davenport_grid_layer()
            return

        if not hasattr(self, 'davenport_results') or not self.davenport_results:
            return
            
        from qgis.core import (
            QgsVectorLayer, QgsFeature, QgsField, QgsSymbol, QgsPalLayerSettings, 
            QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings, Qgis,
            QgsSimpleFillSymbolLayer, QgsRuleBasedRenderer
        )
        from qgis.PyQt.QtCore import QVariant
        from qgis.PyQt.QtGui import QColor

        crs = QgsProject.instance().crs().authid()
        mem_layer = QgsVectorLayer(f"Polygon?crs={crs}", "Griglia Davenport 3x3", "memory")
        pr = mem_layer.dataProvider()
        
        pr.addAttributes([
            QgsField("settore", QVariant.String),
            QgsField("z0", QVariant.Double),
            QgsField("classe", QVariant.String),
            QgsField("is_upwind", QVariant.Int)
        ])
        mem_layer.updateFields()

        wind_dir = self.spin_wind_dir.value()
        deg = wind_dir % 360
        if deg >= 337.5 or deg < 22.5:
            upwind_sector = "N"
        elif 22.5 <= deg < 67.5:
            upwind_sector = "NE"
        elif 67.5 <= deg < 112.5:
            upwind_sector = "E"
        elif 112.5 <= deg < 157.5:
            upwind_sector = "SE"
        elif 157.5 <= deg < 202.5:
            upwind_sector = "S"
        elif 202.5 <= deg < 247.5:
            upwind_sector = "SW"
        elif 247.5 <= deg < 292.5:
            upwind_sector = "W"
        else:
            upwind_sector = "NW"

        feats = []
        for label, data in self.davenport_results.items():
            f = QgsFeature(mem_layer.fields())
            f.setGeometry(data['geometry'])
            f.setAttribute("settore", label)
            f.setAttribute("z0", float(data['z0']))
            f.setAttribute("classe", data['davenport_class'])
            f.setAttribute("is_upwind", 1 if label == upwind_sector else 0)
            feats.append(f)
            
        pr.addFeatures(feats)
        mem_layer.updateExtents()

        symbol_normal = QgsSymbol.defaultSymbol(Qgis.GeometryType.Polygon)
        sym_layer_normal = QgsSimpleFillSymbolLayer.create({
            'outline_color': '#7f8c8d',
            'outline_width': '0.5',
            'outline_style': 'dash',
            'color': '127,140,141,30',
            'style': 'solid'
        })
        symbol_normal.changeSymbolLayer(0, sym_layer_normal)
        
        symbol_upwind = QgsSymbol.defaultSymbol(Qgis.GeometryType.Polygon)
        sym_layer_upwind = QgsSimpleFillSymbolLayer.create({
            'outline_color': '#2980b9',
            'outline_width': '1.5',
            'outline_style': 'solid',
            'color': '41,128,185,70',
            'style': 'solid'
        })
        symbol_upwind.changeSymbolLayer(0, sym_layer_upwind)

        symbol_center = QgsSymbol.defaultSymbol(Qgis.GeometryType.Polygon)
        sym_layer_center = QgsSimpleFillSymbolLayer.create({
            'outline_color': '#27ae60',
            'outline_width': '1.0',
            'outline_style': 'solid',
            'color': '39,174,96,20',
            'style': 'solid'
        })
        symbol_center.changeSymbolLayer(0, sym_layer_center)

        root_rule = QgsRuleBasedRenderer.Rule(None)
        rule_center = QgsRuleBasedRenderer.Rule(symbol_center, 0, 0, '"settore" = \'Center\'', "Centro (Sub Area)")
        rule_upwind = QgsRuleBasedRenderer.Rule(symbol_upwind, 0, 0, '"is_upwind" = 1 AND "settore" != \'Center\'', "Sopravento (Inflow)")
        rule_normal = QgsRuleBasedRenderer.Rule(symbol_normal, 0, 0, '"is_upwind" = 0 AND "settore" != \'Center\'', "Altri settori")
        
        root_rule.appendChild(rule_center)
        root_rule.appendChild(rule_upwind)
        root_rule.appendChild(rule_normal)
        
        renderer = QgsRuleBasedRenderer(root_rule)
        mem_layer.setRenderer(renderer)

        settings = QgsPalLayerSettings()
        settings.isExpression = True
        settings.fieldName = "concat(\"settore\", '\\n', format_number(\"z0\", 4), ' m\\n', \"classe\")"
        settings.geometryGeneratorEnabled = True
        settings.geometryGeneratorType = Qgis.GeometryType.Point
        settings.geometryGenerator = "centroid($geometry)"
        settings.placement = Qgis.LabelPlacement.AroundPoint
        settings.quadOffset = QgsPalLayerSettings.QuadrantOver
        
        text_format = QgsTextFormat()
        text_format.setSize(9.0)
        text_format.setSizeUnit(Qgis.RenderUnit.Points)
        text_format.setColor(QColor(44, 62, 80))
        
        font = text_format.font()
        font.setBold(True)
        text_format.setFont(font)
        
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1.0)
        buffer.setColor(QColor("white"))
        text_format.setBuffer(buffer)
        
        settings.setFormat(text_format)
        
        labeling = QgsVectorLayerSimpleLabeling(settings)
        mem_layer.setLabeling(labeling)
        mem_layer.setLabelsEnabled(True)

        QgsProject.instance().addMapLayer(mem_layer)
        self.btn_draw_davenport_grid.setText(" Rimuovi Griglia dalla Mappa")
