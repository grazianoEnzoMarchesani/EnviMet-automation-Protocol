import os
import re
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFileDialog, QListWidget, QListWidgetItem, QComboBox, 
    QCheckBox, QGroupBox, QGridLayout, QMessageBox, QScrollArea
)
from qgis.core import QgsProject

from ...core.envimet_reader import ENVImetReader

class ENVImetImportSection(QWidget):
    """Section for bulk importing ENVI-met simulation results."""
    
    import_requested = pyqtSignal(list, list, list, object, object, str, str, bool, str)
    
    def __init__(self, parent=None):
        super(ENVImetImportSection, self).__init__(parent)
        self.reader = ENVImetReader()
        self.edt_file_series = [] # list of dicts {'time': str, 'edx': str, 'edt': str}
        self.metadataCache = None
        
        self._setup_ui()
        self._populate_subareas()
        QgsProject.instance().layersAdded.connect(self._populate_subareas)
        QgsProject.instance().layersRemoved.connect(self._populate_subareas)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("Importazione Risultati ENVI-met")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        # Folder Selection
        folder_group = QGroupBox("Cartella di Output Principale (es. ..._output)")
        folder_layout = QHBoxLayout(folder_group)
        self.lbl_folder = QLabel("Nessuna cartella selezionata")
        self.lbl_folder.setWordWrap(True)
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.lbl_folder)
        folder_layout.addWidget(btn_browse)
        
        # Subfolder Selection
        self.cmb_subfolder = QComboBox()
        self.cmb_subfolder.currentIndexChanged.connect(self._on_subfolder_changed)
        folder_layout.addWidget(QLabel("Sottodominio:"))
        folder_layout.addWidget(self.cmb_subfolder)
        
        layout.addWidget(folder_group)

        # Main Selection Area
        selection_layout = QHBoxLayout()
        
        # Times List
        time_group = QGroupBox("Orari (Serie)")
        time_layout = QVBoxLayout(time_group)
        self.list_times = QListWidget()
        self.list_times.setSelectionMode(QListWidget.MultiSelection)
        btn_all_times = QPushButton("Seleziona Tutti")
        btn_all_times.clicked.connect(lambda: self._select_all_list(self.list_times))
        time_layout.addWidget(self.list_times)
        time_layout.addWidget(btn_all_times)
        selection_layout.addWidget(time_group)

        # Variables List
        var_group = QGroupBox("Variabili")
        var_layout = QVBoxLayout(var_group)
        self.list_vars = QListWidget()
        self.list_vars.setSelectionMode(QListWidget.MultiSelection)
        btn_all_vars = QPushButton("Seleziona Tutte")
        btn_all_vars.clicked.connect(lambda: self._select_all_list(self.list_vars))
        var_layout.addWidget(self.list_vars)
        var_layout.addWidget(btn_all_vars)
        selection_layout.addWidget(var_group)

        # Heights List
        height_group = QGroupBox("Altezze (Z)")
        height_layout = QVBoxLayout(height_group)
        self.list_heights = QListWidget()
        self.list_heights.setSelectionMode(QListWidget.MultiSelection)
        btn_all_heights = QPushButton("Seleziona Tutte")
        btn_all_heights.clicked.connect(lambda: self._select_all_list(self.list_heights))
        height_layout.addWidget(self.list_heights)
        height_layout.addWidget(btn_all_heights)
        selection_layout.addWidget(height_group)

        layout.addLayout(selection_layout)

        # Sub-Area & Options
        options_group = QGroupBox("Impostazioni Mappa")
        options_layout = QGridLayout(options_group)
        
        options_layout.addWidget(QLabel("Limita e allinea alla Sub-Area:"), 0, 0)
        self.cmb_subarea = QComboBox()
        options_layout.addWidget(self.cmb_subarea, 0, 1)
        
        self.chk_follow_terrain = QCheckBox("Follow Terrain (Allineamento Terreno)")
        self.chk_follow_terrain.setChecked(True)
        # self.chk_follow_terrain.setEnabled(False) # Keep enabled just in case user really wants flat Z
        options_layout.addWidget(self.chk_follow_terrain, 1, 0, 1, 2)
        
        self.chk_custom_palette = QCheckBox("Usa palette personalizzata (ignora automatica)")
        self.cmb_custom_palette = QComboBox()
        self.cmb_custom_palette.setEnabled(False)
        self.chk_custom_palette.toggled.connect(self.cmb_custom_palette.setEnabled)
        
        # Populate QGIS standard color ramps
        from qgis.core import QgsStyle
        default_style = QgsStyle.defaultStyle()
        color_ramps = default_style.colorRampNames()
        self.cmb_custom_palette.addItems(sorted(color_ramps))
        
        options_layout.addWidget(self.chk_custom_palette, 2, 0)
        options_layout.addWidget(self.cmb_custom_palette, 2, 1)
        
        layout.addWidget(options_group)

        # Import Button
        self.btn_import = QPushButton("Importa in QGIS")
        self.btn_import.setObjectName("ActionBtn")
        self.btn_import.clicked.connect(self._on_import_clicked)
        self.btn_import.setEnabled(False)
        layout.addWidget(self.btn_import)
        
    def _select_all_list(self, list_widget):
        for i in range(list_widget.count()):
            list_widget.item(i).setSelected(True)

    def _populate_subareas(self):
        current_data = self.cmb_subarea.currentData()
        current_text = self.cmb_subarea.currentText()
        
        self.cmb_subarea.blockSignals(True)
        self.cmb_subarea.clear()
        
        project = QgsProject.instance()
        from qgis.core import QgsWkbTypes, QgsVectorLayer
        import os
        
        for layer_id, layer in project.mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                lname = layer.name()
                source = layer.source()
                fetch_name = layer.customProperty("fetch_filename")
                
                is_sub_area = False
                if fetch_name and isinstance(fetch_name, str) and fetch_name.startswith("sub_area") and fetch_name.endswith(".gpkg"):
                    is_sub_area = True
                elif lname.startswith("Sub Area") and lname.endswith("(ENVI-met)"):
                    is_sub_area = True
                elif source and "sub_area" in os.path.basename(source) and source.endswith(".gpkg"):
                    is_sub_area = True
                    
                if not is_sub_area:
                    continue
                    
                display_name = lname
                filename = ""
                if fetch_name and isinstance(fetch_name, str):
                    filename = fetch_name
                elif source:
                    filename = os.path.basename(source.split("|")[0])
                    
                if filename == "sub_area.gpkg":
                    display_name = "default"
                elif filename.startswith("sub_area_") and filename.endswith(".gpkg"):
                    display_name = filename[len("sub_area_"):-len(".gpkg")]
                else:
                    import re
                    m = re.match(r'^Sub Area\s+(.*?)\s*\(ENVI-met\)$', lname)
                    if m:
                        display_name = m.group(1).strip()
                    else:
                        display_name = "default"
                        
                # Try to extract from feature attribute if fallback is used
                if display_name == "default" and filename != "sub_area.gpkg" and layer.featureCount() > 0:
                    try:
                        feat = next(layer.getFeatures())
                        if layer.fields().indexFromName("name") != -1:
                            attr_name = feat.attribute("name")
                            if attr_name:
                                display_name = str(attr_name)
                    except StopIteration:
                        pass
                        
                self.cmb_subarea.addItem(display_name, layer.id())

        if current_data:
            idx = self.cmb_subarea.findData(current_data)
            if idx >= 0:
                self.cmb_subarea.setCurrentIndex(idx)
        elif current_text:
            idx = self.cmb_subarea.findText(current_text)
            if idx >= 0:
                self.cmb_subarea.setCurrentIndex(idx)
                
        self.cmb_subarea.blockSignals(False)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleziona cartella principale output ENVI-met")
        if not folder:
            return
            
        self.lbl_folder.setText(folder)
        
        # Trova tutte le sottocartelle che contengono file .EDX
        subfolders = []
        for d in os.listdir(folder):
            d_path = os.path.join(folder, d)
            if os.path.isdir(d_path):
                has_edx = any(f.endswith('.EDX') or f.endswith('.edx') for f in os.listdir(d_path))
                if has_edx:
                    subfolders.append(d)
                    
        self.cmb_subfolder.blockSignals(True)
        self.cmb_subfolder.clear()
        if not subfolders:
            # Fallback in case they selected the subfolder directly
            has_edx = any(f.endswith('.EDX') or f.endswith('.edx') for f in os.listdir(folder))
            if has_edx:
                self.cmb_subfolder.addItem("/", folder)
            else:
                QMessageBox.warning(self, "Attenzione", "Nessun file EDX trovato in questa cartella o nelle sue sottocartelle.")
        else:
            for sf in subfolders:
                self.cmb_subfolder.addItem(sf, os.path.join(folder, sf))
        self.cmb_subfolder.blockSignals(False)
        
        if self.cmb_subfolder.count() > 0:
            self._scan_folder(self.cmb_subfolder.itemData(0))

    def _on_subfolder_changed(self, index):
        if index >= 0:
            folder = self.cmb_subfolder.itemData(index)
            self._scan_folder(folder)

    def _scan_folder(self, folder):
        self.list_times.clear()
        self.list_vars.clear()
        self.list_heights.clear()
        self.edt_file_series.clear()
        self.metadataCache = None
        self.btn_import.setEnabled(False)
        
        # Regex to match files like: ProjectName_AT_2024-01-01_12.00.00.EDX
        regex = re.compile(r'^(.+?)_([A-Z]+)_(\d{4}-\d{2}-\d{2})(?:_(\d{2}\.\d{2}\.\d{2}))?\.(EDT|EDX)$', re.IGNORECASE)
        
        file_pairs = {}
        
        for f in os.listdir(folder):
            match = regex.match(f)
            if match:
                name, vtype, date, time, ext = match.groups()
                # We usually want atmosphere or surface outputs. Let's not filter strictly by AT unless needed
                # The user script getFileCoupleSeries groups them.
                key = f"{name}_{vtype}_{date}_{time}"
                if key not in file_pairs:
                    file_pairs[key] = {}
                file_pairs[key][ext.upper()] = os.path.join(folder, f)
                file_pairs[key]['time_str'] = f"{date} {time}" if time else date
                
        # Filter pairs that have both EDX and EDT
        valid_pairs = [v for k, v in file_pairs.items() if 'EDX' in v and 'EDT' in v]
        
        if not valid_pairs:
            QMessageBox.warning(self, "Attenzione", "Nessuna coppia EDX/EDT trovata nella cartella.")
            return
            
        # Sort by time
        valid_pairs.sort(key=lambda x: x['time_str'])
        self.edt_file_series = valid_pairs
        
        for pair in valid_pairs:
            item = QListWidgetItem(pair['time_str'])
            item.setData(Qt.UserRole, pair)
            self.list_times.addItem(item)
            
        # Read the first EDX to get variables and heights
        first_edx = valid_pairs[0]['EDX']
        try:
            self.metadataCache = self.reader.parse_edx(first_edx)
            
            # Variables
            for i, var_name in enumerate(self.metadataCache['variable_names']):
                item = QListWidgetItem(var_name)
                item.setData(Qt.UserRole, i)
                self.list_vars.addItem(item)
                
            # Heights
            z_centroids = self.metadataCache.get('z_centroids', [])
            for z in range(self.metadataCache['nr_zdata']):
                h_val = f"{z_centroids[z]:.2f} m" if z < len(z_centroids) else "N/A"
                item = QListWidgetItem(f"{h_val} (Z={z})")
                item.setData(Qt.UserRole, {"z": z, "h_val": h_val})
                self.list_heights.addItem(item)
                
            self.btn_import.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile leggere il file EDX:\n{e}")

    def _on_import_clicked(self):
        selected_times = [item.data(Qt.UserRole) for item in self.list_times.selectedItems()]
        selected_vars = [(item.data(Qt.UserRole), item.text()) for item in self.list_vars.selectedItems()]
        selected_heights = [item.data(Qt.UserRole) for item in self.list_heights.selectedItems()]
        
        if not selected_times or not selected_vars or not selected_heights:
            QMessageBox.warning(self, "Attenzione", "Seleziona almeno un orario, una variabile e un'altezza.")
            return
            
        layer_id = self.cmb_subarea.currentData()
        sub_name = self.cmb_subarea.currentText()
        if not layer_id:
            QMessageBox.warning(self, "Attenzione", "Seleziona un layer Sub-Area valido.")
            return
            
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer or layer.featureCount() == 0:
            QMessageBox.warning(self, "Attenzione", "Il layer Sub-Area non contiene feature.")
            return
            
        feat = next(layer.getFeatures())
        sub_area_geom = feat.geometry()
        crs_authid = layer.crs().authid()

        # Build sub_info with center coordinates directly from the layer feature
        center = sub_area_geom.centroid().asPoint()
        sub_info = {
            "center_x": center.x(),
            "center_y": center.y(),
            "name": sub_name
        }

        if not sub_area_geom:
            QMessageBox.warning(self, "Errore", "Geometria della Sub Area non valida.")
            return

        # Prepare output directory
        project_path = QgsProject.instance().fileName()
        if project_path:
            project_dir = os.path.dirname(project_path)
            out_dir = os.path.join(project_dir, "envimet_imported_rasters")
        else:
            base_folder = os.path.dirname(selected_times[0]['EDX'])
            out_dir = os.path.join(base_folder, "imported_rasters")

        # Format the selected times as tuples for the task
        edt_files = [(pair['EDX'], pair['EDT'], pair['time_str']) for pair in selected_times]
        variables = selected_vars
        heights = selected_heights
        follow_terrain = self.chk_follow_terrain.isChecked()

        custom_palette = ""
        if self.chk_custom_palette.isChecked():
            custom_palette = self.cmb_custom_palette.currentText()

        # Emit signal to let the dashboard handle the task scheduling
        self.import_requested.emit(edt_files, variables, heights, sub_area_geom, sub_info, crs_authid, out_dir, follow_terrain, custom_palette)

    def set_enabled(self, enabled):
        self.setEnabled(enabled)
