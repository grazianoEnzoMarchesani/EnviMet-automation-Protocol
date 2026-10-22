import os
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QCheckBox, QMessageBox,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFormLayout, QGridLayout
)
from qgis.core import QgsApplication, QgsProject
from qgis.gui import QgsCollapsibleGroupBox

from ..mixins.help_mixin import HelpMixin

class ENVImetExportSection(QgsCollapsibleGroupBox, HelpMixin):
    """Section 3: ENVI-met Integration - Data transformation controls."""
    
    # Signals
    conversion_requested = pyqtSignal()
    migration_requested = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__("3. Preparazione ENVI-met", parent)
        
        # Internal state
        self.custom_mapping = None
        self.custom_widths = None
        self.custom_road_materials = None
        self.custom_plant_mapping = None
        self.custom_tree_settings = None
        self.custom_building_settings = None
        
        # UI Elements pre-initialization
        self.btn_landuse_config = None
        self.btn_roads_config = None
        self.btn_plants_config = None
        self.btn_buildings_config = None
        self.chk_level_terrain = None
        self.chk_envimet_v6 = None
        self.btn_convert = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Initialize the UI components."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 10, 5, 10)
        self.main_layout.setSpacing(10)
        

        # --- Section 2: Azioni ---
        self.action_layout = QVBoxLayout()
        self.action_layout.setSpacing(12)
        
        # 1. Configuration Buttons (Grid 2x2)
        config_container = QWidget()
        config_grid = QGridLayout(config_container)
        config_grid.setContentsMargins(5, 5, 5, 5)
        config_grid.setSpacing(8)
        
        self.btn_landuse_config = QPushButton(" Configura Land Use")
        self.btn_landuse_config.setObjectName("LightButton")
        self.btn_landuse_config.setMinimumHeight(35)
        
        self.btn_roads_config = QPushButton(" Configura Strade")
        self.btn_roads_config.setObjectName("LightButton")
        self.btn_roads_config.setMinimumHeight(35)
        
        self.btn_plants_config = QPushButton(" Configura Vegetazione")
        self.btn_plants_config.setObjectName("LightButton")
        self.btn_plants_config.setMinimumHeight(35)
        
        self.btn_buildings_config = QPushButton(" Configura Edifici")
        self.btn_buildings_config.setObjectName("LightButton")
        self.btn_buildings_config.setMinimumHeight(35)
        
        config_grid.addWidget(self.btn_landuse_config, 0, 0)
        config_grid.addWidget(self.btn_roads_config, 0, 1)
        config_grid.addWidget(self.btn_plants_config, 1, 0)
        config_grid.addWidget(self.btn_buildings_config, 1, 1)
        
        self.action_layout.addWidget(config_container)
        
        # 2. Options
        self.chk_level_terrain = QCheckBox("Livella terreno sotto gli edifici (Pads)")
        self.chk_level_terrain.setChecked(True)
        self.action_layout.addWidget(self.chk_level_terrain)

        self.chk_envimet_v6 = QCheckBox("Usa catalogo piante 3D ENVI-met 6")
        self.chk_envimet_v6.setToolTip(
            "Se attivo, utilizza esclusivamente le nuove piante 3D Abstract di ENVI-met 6\n"
            "(Small 5m, Regular 10m, Medium 15m, Large 20m) invece del vecchio catalogo v5."
        )
        self.chk_envimet_v6.setChecked(True)
        self.chk_envimet_v6.toggled.connect(self._on_envimet_v6_toggled)
        self.action_layout.addWidget(self.chk_envimet_v6)

        # 3. Main Action Button
        self.btn_convert = QPushButton(" Prepara Dati per ENVI-met")
        self.btn_convert.setObjectName("DarkButton")
        self.btn_convert.setMinimumHeight(42)
        self.action_layout.addWidget(self.btn_convert)
        
        # 3.5 LOAD / UPDATE LAYERS BUTTON
        self.btn_load_layers = QPushButton(" Carica / Aggiorna Layer Preparati")
        self.btn_load_layers.setObjectName("PrimaryButton")
        self.btn_load_layers.setMinimumHeight(38)
        self.action_layout.addWidget(self.btn_load_layers)
        
        # 4. FIX ALIGNMENT BUTTON
        self.btn_fix_alignment = QPushButton(" Corregge Allineamento (Migra a UTM)")
        self.btn_fix_alignment.setObjectName("SecondaryButton")
        self.btn_fix_alignment.setMinimumHeight(38)
        self.btn_fix_alignment.hide() 
        self.action_layout.addWidget(self.btn_fix_alignment)
        
        self.main_layout.addLayout(self.action_layout)
        self.main_layout.addSpacing(5)
        
        # Connections
        self.btn_convert.clicked.connect(self.conversion_requested.emit)
        self.btn_load_layers.clicked.connect(self._load_prepared_layers)
        self.btn_landuse_config.clicked.connect(self._open_mapping_dialog)
        self.btn_roads_config.clicked.connect(self._open_road_dialog)
        self.btn_plants_config.clicked.connect(self._open_plant_dialog)
        self.btn_buildings_config.clicked.connect(self._open_building_dialog)
        self.btn_fix_alignment.clicked.connect(self._run_migration)

    def _get_dashboard(self):
        """Helper to navigate up to the EnviProtocolDashboard instance."""
        dashboard = self.parent()
        from ..dashboard import EnviProtocolDashboard
        p = dashboard
        while p and not isinstance(p, EnviProtocolDashboard):
            p = p.parent()
        return p

    def _open_mapping_dialog(self):
        """Opens the land use customization dialog."""
        from ..dialogs.mapping_dialog import MappingCustomizationDialog
        dlg = MappingCustomizationDialog(self.custom_mapping, self)
        # QGIS 4 compatibility (exec_ -> exec)
        res = dlg.exec() if hasattr(dlg, 'exec') else dlg.exec_()
        if res:
            self.custom_mapping = dlg.get_mapping()

    def _open_road_dialog(self):
        """Opens the road network customization dialog."""
        from ..dialogs.road_customization_dialog import RoadCustomizationDialog
        dlg = RoadCustomizationDialog(self.custom_widths, self.custom_road_materials, self)
        # QGIS 4 compatibility (exec_ -> exec)
        res = dlg.exec() if hasattr(dlg, 'exec') else dlg.exec_()
        if res:
            self.custom_widths, self.custom_road_materials = dlg.get_settings()

    def _on_envimet_v6_toggled(self, checked):
        """Sync ENVI-met 6 catalog preference and refresh Attribute Modification tree if open."""
        if self.custom_tree_settings is not None:
            self.custom_tree_settings["envimet_v6"] = checked
            if checked and self.custom_tree_settings.get("shape") == "Heart-shaped":
                self.custom_tree_settings["shape"] = "Random"
        dashboard = self._get_dashboard()
        if dashboard and hasattr(dashboard, "attr_mod_section"):
            dashboard.attr_mod_section.refresh_tree_if_vegetation()

    def _open_plant_dialog(self):
        """Opens the plants customization dialog (Simple + 3D)."""
        from ..dialogs.plant_customization_dialog import PlantCustomizationDialog
        current_settings = self.get_tree_settings()
        dlg = PlantCustomizationDialog(self.custom_plant_mapping, current_settings, self)
        # QGIS 4 compatibility (exec_ -> exec)
        res = dlg.exec() if hasattr(dlg, 'exec') else dlg.exec_()
        if res:
            self.custom_plant_mapping, self.custom_tree_settings = dlg.get_settings()
            if self.chk_envimet_v6 is not None:
                self.chk_envimet_v6.blockSignals(True)
                self.chk_envimet_v6.setChecked(self.custom_tree_settings.get("envimet_v6", True))
                self.chk_envimet_v6.blockSignals(False)
                self._on_envimet_v6_toggled(self.chk_envimet_v6.isChecked())

    def _open_building_dialog(self):
        """Opens the building customization dialog."""
        from ..dialogs.building_customization_dialog import BuildingCustomizationDialog
        dlg = BuildingCustomizationDialog(self.custom_building_settings, self)
        # QGIS 4 compatibility (exec_ -> exec)
        res = dlg.exec() if hasattr(dlg, 'exec') else dlg.exec_()
        if res:
            self.custom_building_settings = dlg.get_settings()

    def get_landuse_mapping(self):
        """Returns the current landuse mapping (None if default)."""
        return self.custom_mapping

    def get_road_settings(self):
        """Returns the current road widths and materials."""
        return self.custom_widths, self.custom_road_materials
    
    def get_plant_mapping(self):
        """Returns the custom plant mapping (None if default)."""
        return self.custom_plant_mapping

    def is_envimet_v6(self):
        """Returns True if ENVI-met 6 3D plants catalog is selected."""
        return self.chk_envimet_v6.isChecked() if self.chk_envimet_v6 else True

    def get_tree_settings(self):
        """Returns the custom 3D tree settings (including envimet_v6 flag)."""
        v6_enabled = self.is_envimet_v6()
        if self.custom_tree_settings is None:
            return {
                "type": "Deciduous Trees",
                "shape": "Random",
                "density_mode": "auto",
                "tcd_threshold": 70,
                "density_multiplier": 1.0,
                "exclude_barren_water": True,
                "exclude_grassland": True,
                "envimet_v6": v6_enabled
            }
        settings = self.custom_tree_settings.copy()
        settings["envimet_v6"] = v6_enabled
        if v6_enabled and settings.get("shape") == "Heart-shaped":
            settings["shape"] = "Random"
        return settings

    def get_building_settings(self):
        """Returns the current building materials and greenings (None if default)."""
        return self.custom_building_settings
    
    def is_leveling_enabled(self):
        """Returns True if terrain leveling is requested."""
        return self.chk_level_terrain.isChecked()

    def set_enabled(self, enabled):
        """Toggle section interactive state."""
        self.btn_convert.setEnabled(enabled)
        self.btn_load_layers.setEnabled(enabled)
        self.btn_fix_alignment.setEnabled(enabled)
        if self.chk_level_terrain:
            self.chk_level_terrain.setEnabled(enabled)
        if self.chk_envimet_v6:
            self.chk_envimet_v6.setEnabled(enabled)
        self.btn_landuse_config.setEnabled(enabled)
        self.btn_roads_config.setEnabled(enabled)
        self.btn_plants_config.setEnabled(enabled)
        self.btn_buildings_config.setEnabled(enabled)
        self.setEnabled(enabled)

    def showEvent(self, event):
        """Show/hide migration button on section activation."""
        if QgsProject.instance().fileName():
            self.btn_fix_alignment.show()
        else:
            self.btn_fix_alignment.hide()
        super().showEvent(event)

    def _run_migration(self):
        """Execute the project migration to UTM."""
        # We need the extent from the setup section
        dashboard = self._get_dashboard()
        if not dashboard or not hasattr(dashboard, "setup_section"):
            QMessageBox.warning(self, "Errore", "Impossibile trovare la sezione di configurazione area.")
            return

        extent, crs = dashboard.setup_section.get_extent_and_crs()
        if not extent or not crs:
            QMessageBox.warning(self, "Errore", "Nessuna area o CRS base rilevato. Cattura l'estensione nella Sezione 1.")
            return

        from ...core.utils import get_target_crs_for_extent
        target_crs_auth = get_target_crs_for_extent(extent, crs)
        
        reply = QMessageBox.question(
            self, "Migrazione Progetto",
            f"Tutti i dati preparati (.gpkg, .tif) verranno riproiettati in {target_crs_auth}.\n"
            "Questa operazione sovrascriverà i file esistenti per correggere l'allineamento.\n\n"
            "Procedere?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.migration_requested.emit(target_crs_auth)

    def _apply_sub_area_styling(self, layer):
        """
        Apply custom styling to the sub area layer:
        - Fill: None (hollow)
        - Stroke: Deterministic color based on sub-area name (1.2mm) for high visibility
        - Centroid: Arrow pointing to the local grid North (rotated by the rotation angle)
        - Label: Sub-area name and rotation angle (in degrees) for clear identification
        """
        from qgis.PyQt.QtGui import QColor
        from qgis.core import QgsSimpleFillSymbolLayer, QgsSymbol, QgsSingleSymbolRenderer
        from ...core.utils import get_color_for_sub_area
        
        # Get sub-area name
        filename = layer.customProperty("fetch_filename") or ""
        sub_name = "default"
        if filename.startswith("sub_area_") and filename.endswith(".gpkg"):
            sub_name = filename[len("sub_area_"):-len(".gpkg")]
        elif filename == "sub_area.gpkg":
            sub_name = "default"
        else:
            # Fallback to parsing layer name
            lname = layer.name()
            if lname.startswith("Sub Area ") and lname.endswith(" (ENVI-met)"):
                sub_name = lname[len("Sub Area "):-len(" (ENVI-met)")]
                
        stroke_color = None
        if layer.featureCount() > 0:
            feat = next(layer.getFeatures())
            if layer.fields().indexFromName("color") != -1:
                col_attr = feat.attribute("color")
                from qgis.PyQt.QtCore import QVariant
                if col_attr and not isinstance(col_attr, QVariant):
                    col_str = str(col_attr).strip()
                    if col_str:
                        stroke_color = QColor(col_str)
                        
        if not stroke_color:
            stroke_color = get_color_for_sub_area(sub_name)
        
        props = {
            'outline_color': f'{stroke_color.red()},{stroke_color.green()},{stroke_color.blue()}',
            'outline_width': '1.2',
            'outline_width_unit': 'MM',
            'outline_style': 'solid',
            'joinstyle': 'bevel',
            'style': 'no' # This makes the polygon hollow
        }
        
        symbol_layer = QgsSimpleFillSymbolLayer.create(props)
        if symbol_layer:
            # Create a fill symbol (polygons use fill symbols)
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.changeSymbolLayer(0, symbol_layer)
            
            # Create centroid fill symbol layer to place a marker at the centroid
            from qgis.core import (
                QgsCentroidFillSymbolLayer, QgsSimpleMarkerSymbolLayer, QgsSymbolLayer,
                QgsProperty, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
                QgsTextFormat, QgsTextBufferSettings, Qgis
            )
            
            centroid_layer = QgsCentroidFillSymbolLayer()
            centroid_layer.setPointOnAllParts(False)
            centroid_layer.setClipPoints(False)
            
            # Create an arrow marker layer rotated by the "rotation" attribute
            marker_props = {
                'name': 'arrow',
                'color': f'{stroke_color.name()}',
                'outline_color': '#2c3e50',
                'outline_width': '0.3',
                'size': '12.0',
                'size_unit': 'MM'
            }
            marker_layer = QgsSimpleMarkerSymbolLayer.create(marker_props)
            marker_layer.setDataDefinedProperty(
                QgsSymbolLayer.PropertyAngle,
                QgsProperty.fromExpression("-1 * \"rotation\"")
            )
            
            # Put the marker layer in a marker symbol (Point symbol)
            marker_symbol = QgsSymbol.defaultSymbol(Qgis.GeometryType.Point)
            marker_symbol.changeSymbolLayer(0, marker_layer)
            
            centroid_layer.setSubSymbol(marker_symbol)
            symbol.appendSymbolLayer(centroid_layer)
            
            # Apply the renderer to the layer
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            
            # Configure and enable labeling (Name and Rotation angle)
            settings = QgsPalLayerSettings()
            settings.isExpression = True
            
            if layer.fields().indexFromName("rotation") != -1:
                settings.fieldName = "concat(\"name\", '\\n(', format_number(\"rotation\", 1), '°)')"
            else:
                settings.fieldName = "\"name\""
                
            # Force the labeling engine to treat the polygon as a point at its centroid,
            # which enables the Point placement offset and quadrant settings to work correctly.
            settings.geometryGeneratorEnabled = True
            settings.geometryGeneratorType = Qgis.GeometryType.Point
            settings.geometryGenerator = "centroid($geometry)"
            
            # Place label below the centroid to avoid overlapping with the arrow
            settings.placement = Qgis.LabelPlacement.AroundPoint
            settings.quadOffset = QgsPalLayerSettings.QuadrantBelow
            settings.yOffset = 8.0
            settings.xOffset = 0.0
            settings.offsetUnits = Qgis.RenderUnit.Millimeters
            
            # Style label text
            text_format = QgsTextFormat()
            text_format.setSize(9.0)
            text_format.setSizeUnit(Qgis.RenderUnit.Points)
            text_format.setColor(QColor(30, 30, 30)) # Dark Charcoal
            
            # Bold font
            font = text_format.font()
            font.setBold(True)
            text_format.setFont(font)
            
            # White buffer (halo) for contrast
            buffer = QgsTextBufferSettings()
            buffer.setEnabled(True)
            buffer.setSize(1.5)
            buffer.setSizeUnit(Qgis.RenderUnit.Points)
            buffer.setColor(QColor("white"))
            text_format.setBuffer(buffer)
            
            settings.setFormat(text_format)
            
            # Apply labeling to the layer
            labeling = QgsVectorLayerSimpleLabeling(settings)
            layer.setLabeling(labeling)
            layer.setLabelsEnabled(True)
            
            layer.triggerRepaint()


    def _apply_surfaces_styling(self, layer):
        """Categorized renderer for soil and surface materials."""
        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsFillSymbol
        from qgis.PyQt.QtGui import QColor
        
        # Color palette for Soil/Soil Profile IDs
        COLOR_MAP = {
            "0200ST": "#2c3e50", # Asphalt
            "0200PG": "#95a5a6", # Concrete Gray
            "0200PP": "#7f8c8d", # Concrete used
            "0200PL": "#bdc3c7", # Concrete Light
            "0200PD": "#34495e", # Concrete Dark
            "0200SL": "#90be6d", # Sandy Loam (Natural)
            "000000": "#8d6e63", # Default Soil (Earthy)
            "0200SL": "#a1887f", # Sandy Loam
            "0200LO": "#5d4037", # Loam
            "0200SD": "#f4d35e", # Sandy Soil
            "0200WW": "#0077b6", # Water
            "0200KK": "#c0392b", # Brick Red
            "0200KG": "#e67e22", # Brick Yellow
            "0200WD": "#795548", # Wood
            "0200DW": "#3e2723", # Dark wood
            "0200BA": "#212f3d", # Basalt
        }
        self._apply_categorized_styling(layer, "ENVI_ID", COLOR_MAP, "#95a5a6", fill_style="solid", outline_color="#ffffff")

    def _apply_plants_styling(self, layer):
        """Categorized renderer for simple plant materials with Dense 3 pattern."""
        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsFillSymbol
        from qgis.PyQt.QtGui import QColor

        COLOR_MAP = {
            "0200XX": "#2ecc71", # Grass 25cm
            "0200XY": "#27ae60", # Grass 50cm
            "0200H1": "#1e8449", # Hedge 1m
            "0200H2": "#145a32", # Hedge 2m
            "0200H4": "#0b5345", # Hedge 4m
            "0200SO": "#f1c40f", # Soja
            "0200LG": "#d4ac0d", # Luzerne
            "0200IV": "#1d8348", # Ivy
        }
        # Using "dense3" for "Compatto 3" and a darker outline for better pattern visibility
        self._apply_categorized_styling(layer, "ENVI_ID", COLOR_MAP, "#2ecc71", fill_style="dense3", outline_color="#2c3e50")

    def _apply_categorized_styling(self, layer, attr_name, color_map, default_color, fill_style="solid", outline_color="#ffffff"):
        """Helper to create a categorized renderer with fallback logic and pattern support."""
        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsFillSymbol
        from qgis.PyQt.QtGui import QColor

        idx_id = layer.fields().indexFromName(attr_name)
        if idx_id == -1: return

        idx_name = layer.fields().indexFromName("Name")
        
        # Collect unique ID -> Name pairs for legend labels
        unique_pairs = {} 
        for f in layer.getFeatures():
            eid = str(f.attribute(attr_name))
            if eid not in unique_pairs:
                name = str(f.attribute("Name")) if idx_name != -1 and f.attribute("Name") else eid
                unique_pairs[eid] = name

        categories = []
        for eid, name in unique_pairs.items():
            color_hex = color_map.get(eid, default_color)
            
            # Smart Fallback if material is unknown in our local map
            if eid not in color_map:
                n_low = name.lower()
                if "asphalt" in n_low or "road" in n_low or "street" in n_low: color_hex = "#2c3e50"
                elif "concrete" in n_low or "pavement" in n_low or "brick" in n_low: color_hex = "#95a5a6"
                elif "water" in n_low: color_hex = "#0077b6"
                elif "grass" in n_low: color_hex = "#90be6d"
                elif "soil" in n_low or "loam" in n_low or "sand" in n_low: color_hex = "#8d6e63"
                elif "plant" in n_low or "hedge" in n_low or "tree" in n_low: color_hex = "#27ae60"

            symbol = QgsFillSymbol.createSimple({
                'color': color_hex,
                'outline_color': outline_color,
                'outline_width': '0.1',
                'outline_width_unit': 'MM',
                'style': fill_style
            })
            category = QgsRendererCategory(eid, symbol, name)
            categories.append(category)

        # Add default category for all other values to prevent disappearance
        default_symbol = QgsFillSymbol.createSimple({
            'color': default_color,
            'outline_color': outline_color,
            'outline_width': '0.1',
            'outline_width_unit': 'MM',
            'style': fill_style
        })
        categories.append(QgsRendererCategory("", default_symbol, "Altro / Default"))
        
        renderer = QgsCategorizedSymbolRenderer(attr_name, categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def _apply_buildings_styling(self, layer):
        """Rule-based renderer for buildings: roof materials + greening overlay."""
        from qgis.core import QgsRuleBasedRenderer, QgsFillSymbol
        from qgis.PyQt.QtGui import QColor

        # 1. Setup Rule-based Root
        root_rule = QgsRuleBasedRenderer.Rule(None)

        # 2. Define Base Rules (Roof Materials) - Multi-rule execution enables overlays
        # Note: Rules are evaluated in order. We put materials first.
        base_materials = [
            ("Tetto in Coppi / Tegole", '"ROOF_ID" = \'0200R1\'', "#c0392b"),
            ("Tetto in Cemento / Technical", '"ROOF_ID" LIKE \'0200C%\'', "#95a5a6"),
            ("Tetto in Vetro / Solare", '"ROOF_ID" LIKE \'0200G%\' OR "ROOF_ID" = \'0200PW\'', "#3498db"),
            ("Tetto Standard / Altro", 'ELSE', "#7f8c8d"),
        ]

        for label, filter_exp, color_hex in base_materials:
            symbol = QgsFillSymbol.createSimple({
                'color': color_hex,
                'outline_color': '#2c3e50',
                'outline_width': '0.2',
                'outline_width_unit': 'MM'
            })
            rule = QgsRuleBasedRenderer.Rule(symbol, label=label, filterExp=filter_exp)
            if filter_exp == "ELSE":
                rule.setIsElse(True)
            root_rule.appendChild(rule)

        # 3. Add Additive Overlay for Greening (drawn on top)
        # Pattern dense4 provides a nice semi-transparent "vegetation" look
        green_symbol = QgsFillSymbol.createSimple({
            'color': '#27ae60',
            'style': 'dense4',
            'outline_style': 'no'
        })
        greening_rule = QgsRuleBasedRenderer.Rule(green_symbol, label="Inverdimento Roof (Greening)", filterExp='"R_GREEN_ID" != \'\' AND "R_GREEN_ID" IS NOT NULL')
        root_rule.appendChild(greening_rule)

        # 4. Apply Renderer
        renderer = QgsRuleBasedRenderer(root_rule)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def _apply_vegetation_styling(self, layer):
        """Advanced styling for 3D vegetation: species colors and proportional canopy size."""
        from qgis.core import (
            QgsCategorizedSymbolRenderer, QgsRendererCategory, 
            QgsMarkerSymbol, QgsProperty, QgsUnitTypes
        )
        from qgis.PyQt.QtGui import QColor

        # 1. Detect dynamic height field from processing output
        f_names = [f.name() for f in layer.fields()]
        h_field = "height"
        for candidate in ["height_1", "SAMPLE", "height_1_1"]:
            if candidate in f_names:
                h_field = candidate
                break

        # 2. Define Species Colors (Prefix-based mapping)
        SPECIES_PALETTE = {
            "02A": "#1b5e20", # Conifers (Dark Green)
            "02C": "#1b5e20", # Conifers (Cylindric)
            "02O": "#2ecc71", # Deciduous (Vibrant)
            "02H": "#2ecc71", # Heart-shaped
            "02S": "#2ecc71", # Spherical
            "01P": "#4caf50", # Palms (v5)
            "02P": "#4caf50", # Palms (v6)
            "OTH": "#228b22", # Default Forest Green
        }

        # Collect unique species in the current layer
        unique_pairs = {}
        for f in layer.getFeatures():
            eid = str(f.attribute("ENVI_ID"))
            if eid not in unique_pairs:
                name = str(f.attribute("Name")) if f.attribute("Name") else eid
                unique_pairs[eid] = name

        categories = []
        for eid, name in unique_pairs.items():
            # Extract category from ID prefix
            prefix = eid[:3]
            color_hex = SPECIES_PALETTE.get(prefix, SPECIES_PALETTE["OTH"])
            
            # Create Marker Symbol (Circle)
            symbol = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': color_hex,
                'outline_color': '#1b5e20',
                'outline_width': '0.2'
            })
            
            # Set size in MAP UNITS (Meters) for realistic scale
            symbol.setSizeUnit(QgsUnitTypes.RenderMapUnits)
            
            # Data-defined size (Expression: Canopy width = Height * 0.7)
            # COALESCE ensures a fallback to 3.0m if height is missing
            expr = f'COALESCE("{h_field}", 3.0) * 0.7'
            symbol.setDataDefinedSize(QgsProperty.fromExpression(expr))
            
            category = QgsRendererCategory(eid, symbol, name)
            categories.append(category)

        # Add a default symbol for "All other values" to prevent objects from disappearing
        default_marker = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'color': SPECIES_PALETTE["OTH"],
            'outline_color': '#1b5e20',
            'outline_width': '0.2'
        })
        default_marker.setSizeUnit(QgsUnitTypes.RenderMapUnits)
        default_marker.setDataDefinedSize(QgsProperty.fromExpression(f'COALESCE("{h_field}", 3.0) * 0.7'))
        
        categories.append(QgsRendererCategory("", default_marker, "Altro / Default"))
        
        # 3. Apply Categorized Renderer
        renderer = QgsCategorizedSymbolRenderer("ENVI_ID", categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def _get_envimet_group(self):
        """Find or create the ENVI-met group at the top of the legend."""
        from qgis.core import QgsProject
        root = QgsProject.instance().layerTreeRoot()
        group_name = "Modello ENVI-met" # Localized name for the section
        
        group = root.findGroup(group_name)
        if not group:
            # Insert at the very top (index 0)
            group = root.insertGroup(0, group_name)
        else:
            # Ensure it stays at the top if it already exists
            first_child = root.children()[0] if root.children() else None
            if first_child and first_child.name() != group_name:
                # Move to top via robust clone and remove pattern
                group_node = root.findGroup(group_name)
                cloned_group = group_node.clone()
                root.insertChildNode(0, cloned_group)
                root.removeChildNode(group_node)
                group = root.findGroup(group_name)
            
        return group

    def _reorder_envimet_layers(self, group):
        """Enforce internal Z-order within the group: Sub Area > Vegetation > Buildings > Plants > Surfaces > DTM."""
        from ...core.constants import FileNames
        
        # Desired Order (from top to bottom of the legend)
        ordered_filenames = [
            FileNames.EM_VEGETATION,
            FileNames.EM_BUILDINGS,
            FileNames.EM_SIMPLE_PLANTS,
            FileNames.EM_SURFACES,
            FileNames.DTM
        ]
        
        # Map current nodes in group by their identification property
        nodes_map = {}
        sub_nodes = []
        for node in group.children():
            if hasattr(node, "layer") and node.layer():
                fname = node.layer().customProperty("fetch_filename")
                if fname:
                    if fname.startswith("sub_area"):
                        sub_nodes.append((fname, node))
                    else:
                        nodes_map[fname] = node

        # Re-insert children at the top in reverse order so the list order is preserved from top down
        # 1. Non-subarea layers in reverse order: DTM -> Surfaces -> Plants -> Buildings -> Vegetation
        for fname in reversed(ordered_filenames):
            if fname in nodes_map:
                node = nodes_map[fname]
                cloned_node = node.clone()
                group.insertChildNode(0, cloned_node)
                group.removeChildNode(node)
                
        # 2. Subarea layers on top of everything
        for fname, node in sub_nodes:
            cloned_node = node.clone()
            group.insertChildNode(0, cloned_node)
            group.removeChildNode(node)

    def _load_prepared_layers(self, only_filename=None):
        """Scan the export directory and add/refresh layers in QGIS."""
        from ...core.constants import FolderNames, FileNames
        from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsProject
        from qgis.PyQt.QtWidgets import QMessageBox

        project = QgsProject.instance()
        project_path = project.fileName()
        if not project_path:
             QMessageBox.warning(self, "Errore", "Salva il progetto QGIS prima di procedere.")
             return 0

        project_dir = os.path.dirname(project_path)
        project_name = os.path.splitext(os.path.basename(project_path))[0]
        root_data_dir = os.path.join(project_dir, f"EnviProtocol+{project_name}")
        export_dir = os.path.join(root_data_dir, FolderNames.ENVIMET)

        if not os.path.exists(export_dir):
            QMessageBox.information(self, "Info", "Cartella export non trovata. Esegui prima la preparazione dei dati.")
            return 0

        # Define all standard layers we handle
        filenames = [
            FileNames.EM_VEGETATION,
            FileNames.EM_BUILDINGS,
            FileNames.EM_SIMPLE_PLANTS,
            FileNames.EM_SURFACES,
            FileNames.DTM
        ]
        
        # Scan for subareas dynamically
        subarea_filenames = []
        if os.path.exists(export_dir):
            for filename in os.listdir(export_dir):
                if filename.startswith("sub_area") and filename.endswith(".gpkg"):
                    subarea_filenames.append(filename)
                    
        if only_filename:
            if only_filename in filenames or only_filename in subarea_filenames:
                filenames = [only_filename]
            else:
                return 0
        else:
            # Prepend subareas to the list so they load first
            filenames = subarea_filenames + filenames

        # Ensure the group exists at the top
        group = self._get_envimet_group()

        count = 0
        for filename in filenames:
            path = os.path.join(export_dir, filename)
            
            if not os.path.exists(path):
                continue
            
            # Find if layer already exists in the project
            existing_layer = None
            norm_target = os.path.normcase(os.path.normpath(path))
            for lyr in project.mapLayers().values():
                lyr_src = lyr.source().split("|")[0] if lyr.source() else ""
                if lyr_src and os.path.normcase(os.path.normpath(lyr_src)) == norm_target:
                    existing_layer = lyr
                    break
            
            if existing_layer:
                # Ensure it's in the group and has the ID property
                existing_layer.setCustomProperty("fetch_filename", filename)
                node = project.layerTreeRoot().findLayer(existing_layer.id())
                if node and node.parent() != group:
                    # Robust move to group
                    cloned_node = node.clone()
                    group.addChildNode(cloned_node)
                    node.parent().removeChildNode(node)

                # Update style
                if filename.startswith("sub_area"):
                    self._apply_sub_area_styling(existing_layer)
                elif filename == FileNames.EM_SURFACES:
                    self._apply_surfaces_styling(existing_layer)
                elif filename == FileNames.EM_SIMPLE_PLANTS:
                    self._apply_plants_styling(existing_layer)
                elif filename == FileNames.EM_BUILDINGS:
                    self._apply_buildings_styling(existing_layer)
                elif filename == FileNames.EM_VEGETATION:
                    self._apply_vegetation_styling(existing_layer)
                    
                if hasattr(existing_layer, "dataProvider"):
                    existing_layer.dataProvider().reloadData()
                existing_layer.triggerRepaint()
                count += 1
            else:
                # Handle new layer creation
                name = filename.replace("_", " ").title() + " (ENVI-met)"
                if filename.startswith("sub_area"):
                    if filename == FileNames.EM_SUB_AREA:
                        name = "Sub Area (ENVI-met)"
                    else:
                        sub_name = filename[len("sub_area_"):-len(".gpkg")]
                        name = f"Sub Area {sub_name} (ENVI-met)"
                elif filename == FileNames.EM_VEGETATION: name = "Vegetazione 3D (ENVI-met)"
                elif filename == FileNames.EM_BUILDINGS: name = "Edifici Preparati (ENVI-met)"
                elif filename == FileNames.EM_SIMPLE_PLANTS: name = "Piante Semplici (ENVI-met)"
                elif filename == FileNames.EM_SURFACES: name = "Superfici (ENVI-met)"
                elif filename == FileNames.DTM: name = "Topografia DTM (ENVI-met)"

                if filename == FileNames.DTM:
                    new_layer = QgsRasterLayer(path, name)
                else:
                    new_layer = QgsVectorLayer(path, name, "ogr")
                
                if new_layer.isValid():
                    new_layer.setCustomProperty("fetch_filename", filename)
                    # Add to project without auto-legend placement
                    project.addMapLayer(new_layer, False)
                    # Add explicitly to our group
                    group.addLayer(new_layer)

                    # Apply Styling
                    if filename.startswith("sub_area"):
                        self._apply_sub_area_styling(new_layer)
                    elif filename == FileNames.EM_SURFACES:
                        self._apply_surfaces_styling(new_layer)
                    elif filename == FileNames.EM_SIMPLE_PLANTS:
                        self._apply_plants_styling(new_layer)
                    elif filename == FileNames.EM_BUILDINGS:
                        self._apply_buildings_styling(new_layer)
                    elif filename == FileNames.EM_VEGETATION:
                        self._apply_vegetation_styling(new_layer)
                        
                    count += 1

        # Finalize grouping and order
        self._reorder_envimet_layers(group)
        
        dashboard = self._get_dashboard()
        if dashboard and hasattr(dashboard, "sub_area_mod_section"):
            dashboard.sub_area_mod_section.load_sub_areas_from_disk()
        
        if count > 0:
            QMessageBox.information(self, "Successo", f"Processati {count} layer nel gruppo 'Modello ENVI-met'.")
        
        return count
