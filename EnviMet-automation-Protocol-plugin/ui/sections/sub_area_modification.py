import os
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QCheckBox, QMessageBox,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout
)
from qgis.core import QgsApplication, QgsProject
from qgis.gui import QgsCollapsibleGroupBox

from ..mixins.help_mixin import HelpMixin
from ..widgets.sub_area_tool import SubAreaMapTool, SubAreaStatus

class SubAreaModificationSection(QgsCollapsibleGroupBox, HelpMixin):
    """Section 4: Sub-Area Modification - Interactive geometry controls."""
    
    def __init__(self, parent=None):
        super().__init__("4. Modifica Sub-Area (Area Modello)", parent)
        
        self.sub_area_tool = None
        self.sub_area_state = None # To persist across activations
        
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
            
            self.sub_area_tool = SubAreaMapTool(dashboard.iface.mapCanvas(), extent, crs, initial_state=self.sub_area_state)
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

    def _update_sub_area_params(self):
        if not self.sub_area_tool: return
        
        # Live calculation of grid elements for UX feedback
        w, h, g = self.spin_width.value(), self.spin_height.value(), self.spin_grid.value()
        if g > 0:
            nx, ny = int(w / g), int(h / g)
            total = nx * ny
            
            preview_active = self.chk_preview.isChecked()
            self.lbl_grid_stats.setText(f"{nx} × {ny} ➜ {total:,} elementi".replace(",", "."))
        
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

        subarea_path = os.path.join(export_dir, FileNames.EM_SUB_AREA)
        crs_id = crs if isinstance(crs, str) else crs.authid()
        
        manager = ENVImetManager(dashboard.iface)
        ok, msg = manager.prepare_sub_area(
            extent, crs_id, subarea_path, geometry=geom
        )

        if ok:
            # Automictally deactivate the tool and hide params on success
            self.btn_activate_tool.setChecked(False)
            
            # Delegate loading back to the dashboard/envimet_section if necessary, 
            # but for now we can call it if we have a reference.
            if hasattr(dashboard, "envimet_section"):
                dashboard.envimet_section._load_prepared_layers(FileNames.EM_SUB_AREA)
            QMessageBox.information(self, "Sub Area Generata", "Il layer 'Sub Area (ENVI-met)' è stato creato/aggiornato con successo.")
        else:
            QMessageBox.critical(self, "Errore", f"Impossibile generare la Sub Area: {msg}")
