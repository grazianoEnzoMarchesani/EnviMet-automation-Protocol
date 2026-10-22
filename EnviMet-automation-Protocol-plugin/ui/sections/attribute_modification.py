import os
import json
from qgis.PyQt.QtCore import Qt, pyqtSignal, QEvent
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QCheckBox, QMessageBox,
    QLineEdit, QComboBox, QTreeWidget, QTreeWidgetItem,
    QGroupBox, QAbstractItemView, QStackedWidget, QButtonGroup,
    QToolButton
)
from qgis.core import QgsProject, QgsApplication, Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox

from ..mixins.help_mixin import HelpMixin
from ...core.constants import FileNames

class ClickableLabel(QLabel):
    """A label that emits a clicked signal."""
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

class ClickableLineEdit(QLineEdit):
    """A line edit that emits a clicked signal when focused."""
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

class AttributeModificationSection(QgsCollapsibleGroupBox, HelpMixin):
    """Section 5: Attribute Modification - Batch edit Envi_id and Name."""
    
    def __init__(self, parent=None):
        super().__init__("5. Modifica Attributi Elementi", parent)
        
        self.iface = parent.iface if hasattr(parent, "iface") else None
        self.db_data = self._load_db()
        self.current_layer = None
        self.active_slot_id = "wall" # Track active slot for buildings
        
        self._setup_ui()

        # Connect QGIS signals for automatic refresh whenever the project layers change
        QgsProject.instance().layersAdded.connect(self._refresh_layers)
        QgsProject.instance().layersRemoved.connect(self._refresh_layers)
        
    def _load_db(self):
        """Load envimet_db.json."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "envimet_db.json")
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            QgsMessageLog.logMessage(f"Errore caricamento DB ENVI-met: {e}", "EnviProtocol", Qgis.Warning)
            return {}

    def _get_dashboard(self):
        """Helper to navigate up to the EnviProtocolDashboard instance."""
        dashboard = self.parent()
        from ..dashboard import EnviProtocolDashboard
        p = dashboard
        while p and not isinstance(p, EnviProtocolDashboard):
            p = p.parent()
        return p

    def _setup_ui(self):
        """Initialize the UI components."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 10, 5, 10)
        self.main_layout.setSpacing(10)

        # 1. Layer Selection
        layer_group = QGroupBox("Target Layer")
        layer_group.setObjectName("SubCard")
        layer_layout = QVBoxLayout(layer_group)
        layer_layout.setContentsMargins(10, 10, 10, 10)
        
        combo_row = QHBoxLayout()
        self.combo_layer = QComboBox()
        self.combo_layer.setMinimumHeight(32)
        self.combo_layer.addItem("Seleziona un layer...", None)
        combo_row.addWidget(self.combo_layer, 1)
        
        # Manual Refresh Button
        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("🔄")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip("Aggiorna la lista dei layer")
        self.btn_refresh.clicked.connect(self._refresh_layers)
        self.btn_refresh.setStyleSheet("""
            QToolButton {
                background-color: #ffffff;
                border: 1px solid #dfe4ea;
                border-radius: 6px;
                font-size: 14px;
            }
            QToolButton:hover {
                background-color: #f1f2f6;
                border-color: #3498db;
                color: #3498db;
            }
        """)
        combo_row.addWidget(self.btn_refresh)
        
        layer_layout.addLayout(combo_row)
        
        self.main_layout.addWidget(layer_group)

        # 2. Search and List
        db_group = QGroupBox("Database ENVI-met")
        db_group.setObjectName("SubCard")
        db_layout = QVBoxLayout(db_group)
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Cerca materiale / specie...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._filter_items)
        db_layout.addWidget(self.search_box)
        
        self.tree_items = QTreeWidget()
        self.tree_items.setHeaderHidden(True)
        self.tree_items.setMinimumHeight(200)
        
        try: mode = QAbstractItemView.SelectionMode.SingleSelection
        except AttributeError: mode = QAbstractItemView.SelectionMode.SingleSelection
        self.tree_items.setSelectionMode(mode)
        self.tree_items.itemSelectionChanged.connect(self._on_item_selected)
        db_layout.addWidget(self.tree_items)
        
        self.main_layout.addWidget(db_group)

        # 3. Stacked Widget
        self.stacked_values = QStackedWidget()
        
        # --- Page 1: Generic ---
        self.page_generic = QWidget()
        generic_layout = QVBoxLayout(self.page_generic)
        generic_layout.setContentsMargins(0, 0, 0, 0)
        
        gen_group = QGroupBox("Valori da Assegnare")
        gen_group.setObjectName("SubCard")
        gen_v_layout = QVBoxLayout(gen_group)
        
        id_row = QHBoxLayout()
        lbl_id = QLabel("ENVI_ID:")
        lbl_id.setFixedWidth(80)
        id_row.addWidget(lbl_id)
        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("Es: 0200ST")
        id_row.addWidget(self.edit_id)
        gen_v_layout.addLayout(id_row)
        
        name_row = QHBoxLayout()
        lbl_desc = QLabel("Descrizione:")
        lbl_desc.setFixedWidth(80)
        name_row.addWidget(lbl_desc)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Es: Asphalt Road")
        name_row.addWidget(self.edit_name)
        gen_v_layout.addLayout(name_row)
        
        generic_layout.addWidget(gen_group)
        self.stacked_values.addWidget(self.page_generic)
        
        # --- Page 2: Buildings ---
        self.page_buildings = QWidget()
        building_layout = QVBoxLayout(self.page_buildings)
        building_layout.setContentsMargins(0, 0, 0, 0)
        
        bld_group = QGroupBox("Configurazione Edificio")
        bld_group.setObjectName("SubCard")
        bld_v_layout = QVBoxLayout(bld_group)
        bld_v_layout.setSpacing(5)
        
        # Define Slot helper
        def add_slot(label_text, slot_id, mandatory=True):
            row_frame = QFrame()
            row_frame.setObjectName("SlotRow")
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(6, 6, 6, 6)
            row.setSpacing(8)
            
            lbl = ClickableLabel(label_text)
            lbl.setFixedWidth(80)
            lbl.setCursor(Qt.PointingHandCursor)
            if mandatory: lbl.setStyleSheet("font-weight: bold; color: #3498db;")
            else: lbl.setStyleSheet("color: #7f8c8d;")
            row.addWidget(lbl)
            
            edit = ClickableLineEdit()
            edit.setPlaceholderText("ID")
            edit.setReadOnly(False)
            row.addWidget(edit)
            
            desc = ClickableLineEdit()
            desc.setPlaceholderText("Clicca per selezionare dal DB...")
            desc.setReadOnly(False)
            desc.setStyleSheet("font-size: 10px; color: #7f8c8d;")
            row.addWidget(desc)
            
            if not mandatory:
                # Clear button (only for optional slots) - Styled as a clean tool button
                btn_clear = QToolButton()
                btn_clear.setText("×")
                btn_clear.setFixedSize(22, 22)
                btn_clear.setCursor(Qt.PointingHandCursor)
                btn_clear.setToolTip("Pulisci questo slot")
                btn_clear.setStyleSheet("""
                    QToolButton {
                        background: transparent; 
                        color: #95a5a6; 
                        border-radius: 4px; 
                        font-size: 16px; 
                        font-weight: bold;
                    }
                    QToolButton:hover {
                        background: #e74c3c; 
                        color: white;
                    }
                """)
                btn_clear.clicked.connect(lambda: (edit.clear(), desc.setText("Clicca per selezionare...")))
                row.addWidget(btn_clear)
            else:
                # Add a spacer to keep alignment with optional rows
                row.addSpacing(22)
            
            # Connections to activate slot
            def activate():
                self.active_slot_id = slot_id
                self._update_slot_highlights()
                
                # Refresh tree with context-aware data
                data = self.combo_layer.currentData()
                if data and data[1] == FileNames.EM_BUILDINGS:
                    self._populate_tree(FileNames.EM_BUILDINGS)
            
            lbl.clicked.connect(activate)
            edit.clicked.connect(activate)
            desc.clicked.connect(activate)
            if not mandatory:
                btn_clear.clicked.connect(lambda: (edit.clear(), desc.setText("Clicca per selezionare...")))
            
            bld_v_layout.addWidget(row_frame)
            return edit, desc, row_frame

        self.slots = {}
        e_p, d_p, f_p = add_slot("Parete:", "wall")
        self.slots["wall"] = (e_p, d_p, f_p)
        
        e_r, d_r, f_r = add_slot("Tetto:", "roof")
        self.slots["roof"] = (e_r, d_r, f_r)
        
        e_gw, d_gw, f_gw = add_slot("Inverd. M:", "wgreen", False)
        self.slots["wgreen"] = (e_gw, d_gw, f_gw)
        
        e_gr, d_gr, f_gr = add_slot("Inverd. T:", "rgreen", False)
        self.slots["rgreen"] = (e_gr, d_gr, f_gr)
        
        building_layout.addWidget(bld_group)
        self.stacked_values.addWidget(self.page_buildings)
        
        self.main_layout.addWidget(self.stacked_values)

        # 4. Action Button
        self.btn_apply = QPushButton(" Assegna agli Oggetti Selezionati")
        self.btn_apply.setObjectName("PrimaryButton")
        self.btn_apply.setMinimumHeight(42)
        self.btn_apply.clicked.connect(self._apply_attributes)
        self.main_layout.addWidget(self.btn_apply)
        
        self.main_layout.addStretch()

        self._update_slot_highlights()
        self.combo_layer.currentIndexChanged.connect(self._on_layer_changed)

    def _update_slot_highlights(self):
        """Highlight the currently active slot row."""
        active_qss = "background-color: #f0f7ff; border: 1px solid #3498db; border-radius: 6px;"
        idle_qss = "background-color: transparent; border: 1px solid transparent;"
        
        for sid, (edit, desc, frame) in self.slots.items():
            if sid == self.active_slot_id:
                frame.setStyleSheet(active_qss)
                edit.setStyleSheet("background-color: white; border: 1px solid #3498db;")
                desc.setStyleSheet("background-color: white; border: 1px solid #3498db; font-size: 10px; color: #3498db;")
            else:
                frame.setStyleSheet(idle_qss)
                edit.setStyleSheet("background-color: white; border: 1px solid #dfe4ea;")
                desc.setStyleSheet("background-color: white; border: 1px solid #dfe4ea; font-size: 10px; color: #7f8c8d;")

    # Rest of the methods stay the same...
    def showEvent(self, event):
        self._refresh_layers()
        super().showEvent(event)

    def _refresh_layers(self, *args):
        try:
            if not hasattr(self, 'combo_layer') or self.combo_layer is None:
                return
            # Trigger RuntimeError if the underlying C++ object was deleted
            _ = self.combo_layer.parent()
        except RuntimeError:
            return

        current_text = self.combo_layer.currentText()
        self.combo_layer.blockSignals(True)
        self.combo_layer.clear()
        self.combo_layer.addItem("Seleziona un layer...", None)
        project = QgsProject.instance()
        valid_fnames = {
            FileNames.EM_VEGETATION: "Vegetazione 3D",
            FileNames.EM_BUILDINGS: "Edifici",
            FileNames.EM_SIMPLE_PLANTS: "Piante Semplici",
            FileNames.EM_SURFACES: "Superfici"
        }
        for lyr in project.mapLayers().values():
            if lyr.type() != Qgis.LayerType.VectorLayer: continue
            fname = lyr.customProperty("fetch_filename")
            if fname in valid_fnames:
                name = lyr.name()
                self.combo_layer.addItem(name, (lyr.id(), fname))
                if name == current_text: self.combo_layer.setCurrentText(name)
        self.combo_layer.blockSignals(False)

    def _on_layer_changed(self, index):
        data = self.combo_layer.currentData()
        if not data:
            self.tree_items.clear()
            self.current_layer = None
            return
        lyr_id, fname = data
        self.current_layer = QgsProject.instance().mapLayer(lyr_id)
        
        # Auto-activate layer and selection tool in QGIS
        if self.current_layer and self.iface:
            self.iface.setActiveLayer(self.current_layer)
            self.iface.actionSelect().trigger()
            
        if fname == FileNames.EM_BUILDINGS:
            self.stacked_values.setCurrentWidget(self.page_buildings)
        else:
            self.stacked_values.setCurrentWidget(self.page_generic)
        self._populate_tree(fname)

    def refresh_tree_if_vegetation(self):
        """Re-populates the database tree if the 3D Vegetation layer is currently selected."""
        data = self.combo_layer.currentData() if hasattr(self, "combo_layer") and self.combo_layer else None
        if data and data[1] == FileNames.EM_VEGETATION:
            self._populate_tree(FileNames.EM_VEGETATION)

    def _populate_tree(self, fname):
        self.tree_items.clear()
        if fname == FileNames.EM_BUILDINGS:
            # Select category based on active slot
            if self.active_slot_id in ["wall", "roof"]:
                self._add_category_to_tree("wall_roof_constructions", "Costruzioni (Muri/Tetti)")
            else:
                self._add_category_to_tree("greenings", "Specie Inverdimento")
        else:
            category_key = None
            if fname == FileNames.EM_SURFACES: category_key = "soil_profiles"
            elif fname == FileNames.EM_SIMPLE_PLANTS: category_key = "simple_plants"
            elif fname == FileNames.EM_VEGETATION: category_key = "3d_plants"
            if category_key: self._add_category_to_tree(category_key, "")
        self.tree_items.expandAll()

    def _add_category_to_tree(self, key, label):
        if key not in self.db_data: return
        cat_data = self.db_data[key]
        root = self.tree_items
        if label:
            root = QTreeWidgetItem(self.tree_items, [label])
            root.setSelected(False)
        if key == "3d_plants":
            use_v6 = True
            dashboard = self._get_dashboard()
            if dashboard and hasattr(dashboard, "envimet_section") and hasattr(dashboard.envimet_section, "is_envimet_v6"):
                use_v6 = dashboard.envimet_section.is_envimet_v6()
            for main_cat, main_val in cat_data.items():
                if use_v6 and main_cat == "Abstract":
                    continue
                if not use_v6 and main_cat == "Abstract_v6":
                    continue
                display_cat = "Abstract (ENVI-met 6)" if main_cat == "Abstract_v6" else main_cat
                parent = QTreeWidgetItem(root, [display_cat])
                self._recursive_add_3d(main_val, parent)
        else:
            for sub_cat, items in cat_data.items():
                parent = QTreeWidgetItem(root, [sub_cat])
                for item in items:
                    child = QTreeWidgetItem(parent, [item["name"]])
                    try: role = Qt.ItemDataRole.UserRole
                    except AttributeError: role = Qt.UserRole
                    child.setData(0, role, item["envi_id"])
                    child.setData(1, role, item["name"])

    def _recursive_add_3d(self, data, parent):
        try: role = Qt.ItemDataRole.UserRole
        except AttributeError: role = Qt.UserRole
        if isinstance(data, list):
            for item in data:
                child = QTreeWidgetItem(parent, [f"{item['envi_id']} {item['name']}"])
                child.setData(0, role, item["envi_id"])
                child.setData(1, role, item["name"])
        elif isinstance(data, dict):
            for key, val in data.items():
                child_node = QTreeWidgetItem(parent, [key])
                self._recursive_add_3d(val, child_node)

    def _filter_items(self, text):
        text = text.lower()
        for i in range(self.tree_items.topLevelItemCount()):
            item = self.tree_items.topLevelItem(i)
            self._filter_recursive(item, text)

    def _filter_recursive(self, item, text):
        child_visible = False
        for i in range(item.childCount()):
            if self._filter_recursive(item.child(i), text): child_visible = True
        match = text in item.text(0).lower()
        visible = match or child_visible
        item.setHidden(not visible)
        return visible

    def _on_item_selected(self):
        items = self.tree_items.selectedItems()
        if not items: return
        item = items[0]
        try: role = Qt.ItemDataRole.UserRole
        except AttributeError: role = Qt.UserRole
        eid = item.data(0, role)
        name = item.data(1, role)
        if not eid: return
        if self.stacked_values.currentWidget() == self.page_buildings:
            edit, desc, frame = self.slots[self.active_slot_id]
            edit.setText(eid)
            desc.setText(name)
        else:
            self.edit_id.setText(eid)
            self.edit_name.setText(name)

    def _apply_attributes(self):
        if not self.current_layer:
            QMessageBox.warning(self, "Attenzione", "Seleziona un layer target.")
            return
        selected_ids = self.current_layer.selectedFeatureIds()
        if not selected_ids:
            QMessageBox.information(self, "Info", "Nessun oggetto selezionato nella mappa.")
            return
        data = self.combo_layer.currentData()
        fname = data[1] if data else None
        updates = {}
        if fname == FileNames.EM_BUILDINGS:
            e_p = self.slots["wall"][0].text()
            e_r = self.slots["roof"][0].text()
            if not e_p or not e_r:
                QMessageBox.warning(self, "Attenzione", "Parete e Tetto obbligatori.")
                return
            updates = {
                "ENVI_ID": e_p, "ROOF_ID": e_r,
                "W_GREEN_ID": self.slots["wgreen"][0].text(),
                "R_GREEN_ID": self.slots["rgreen"][0].text(),
                "Name": self.slots["wall"][1].text()
            }
        else:
            eid = self.edit_id.text().strip()
            name = self.edit_name.text().strip()
            if not eid:
                QMessageBox.warning(self, "Attenzione", "Specifica un codice ENVI_ID.")
                return
            updates = {"ENVI_ID": eid, "Name": name}
        reply = QMessageBox.question(self, "Conferma", f"Aggiornare {len(selected_ids)} oggetti?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        self.current_layer.startEditing()
        fields = self.current_layer.fields()
        for fid in selected_ids:
            for field_name, value in updates.items():
                idx = fields.indexFromName(field_name)
                if idx != -1: self.current_layer.changeAttributeValue(fid, idx, value)
        if self.current_layer.commitChanges():
            QMessageBox.information(self, "Successo", f"Aggiornati {len(selected_ids)} oggetti.")
            
            # Reset selection and restore focus to keep the workflow active
            if self.current_layer:
                self.current_layer.removeSelection()
                
            dashboard = self._get_dashboard()
            if dashboard and hasattr(dashboard, "envimet_section"):
                dashboard.envimet_section._load_prepared_layers(fname)
            
            # Re-activate the layer and selection tool after processing
            if self.iface and self.current_layer:
                self.iface.setActiveLayer(self.current_layer)
                self.iface.actionSelect().trigger()
                
            self.current_layer.triggerRepaint()
        else:
            QMessageBox.critical(self, "Errore", f"Errore: {self.current_layer.lastError()}")
            self.current_layer.rollBack()
