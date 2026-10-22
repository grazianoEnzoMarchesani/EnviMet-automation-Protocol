import os
import json
import random
import math
from qgis.PyQt.QtCore import QVariant, QMetaType
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, 
    QgsFields, QgsField, QgsRectangle, QgsCoordinateReferenceSystem,
    Qgis, QgsMessageLog, QgsVectorFileWriter, QgsWkbTypes,
    QgsRasterLayer, QgsCoordinateTransform, QgsApplication,
    QgsPointXY, QgsSpatialIndex
)
from qgis import processing
from .constants import FileNames, ESA_ENVIMET_MAPPING, ROAD_WIDTH_MAPPING

class ENVImetManager:
    """
    Manager class for preparing GIS data for ENVI-met simulations.
    Handles Clipping, Vectorization, and Field Mapping.
    """
    
    def __init__(self, iface=None):
        self.iface = iface
        self._soil_names = self._load_soil_names()

    def _load_soil_names(self):
        """Loads a flat mapping of ID -> Name from envimet_db.json."""
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "envimet_db.json")
        try:
            if not os.path.exists(db_path):
                return {}
            
            with open(db_path, "r", encoding="utf-8") as f:
                db = json.load(f)
            
            mapping = {}
            # Flatten soil_profiles
            for items in db.get("soil_profiles", {}).values():
                for item in items:
                    mapping[item["envi_id"]] = item["name"]
            
            # Add simple_plants
            for items in db.get("simple_plants", {}).values():
                for item in items:
                    mapping[item["envi_id"]] = item["name"]
            return mapping
        except Exception as e:
            self.log(f"Errore caricamento nomi database: {str(e)}", Qgis.Warning)
            return {}

    def log(self, message, level=Qgis.Info):
        QgsMessageLog.logMessage(message, "EnviProtocol", level)

    def _temp_gpkg(self):
        import tempfile, uuid
        return os.path.join(tempfile.gettempdir(), f"envimet_tmp_{uuid.uuid4().hex}.gpkg")

    def get_model_constraints(self, project_dir):
        """
        Analyzes Buildings and DTM to determine optimal ENVI-met constraints.
        Returns (lateral_margin, suggested_vertical_height, max_bld_h, max_dtm_z)
        """
        from .constants import FolderNames, FileNames
        max_bld_h = 20.0  # Default if layer missing
        max_dtm_z = 0.0

        # 1. Scan Buildings for Max Height
        bld_path = ""
        bld_dir = os.path.join(project_dir, FolderNames.TUM)
        if os.path.exists(bld_dir):
            default_bld = os.path.join(bld_dir, FileNames.BUILDINGS)
            if os.path.exists(default_bld):
                bld_path = default_bld
            else:
                for r, d, files in os.walk(bld_dir):
                    for f in files:
                        if f.lower().endswith(".gpkg") and not f.startswith("."):
                            bld_path = os.path.join(r, f)
                            break
                    if bld_path:
                        break
        if bld_path and os.path.exists(bld_path):
            try:
                res = processing.run("qgis:basicstatisticsforfields", {
                    'INPUT': bld_path, 'INPUT_LAYER': bld_path, 'FIELD': 'height', 'FIELD_NAME': 'height', 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                # Check for both 'MAX' and 'MAXIMUM' as keys vary between QGIS versions
                max_bld_h = res.get('MAX', res.get('MAXIMUM', max_bld_h))
            except Exception as e:
                self.log(f"Impossibile leggere altezza edifici: {str(e)}", Qgis.Warning)

        # 2. Scan DTM for Max elevation
        dtm_path = os.path.join(project_dir, FileNames.DTM)
        if not os.path.exists(dtm_path):
             # Try to find a unified DTM or scan tiles
             dtm_dir = os.path.join(project_dir, FolderNames.TINITALY)
             self.log(f"Analisi DTM ricorsiva in: {dtm_dir}")
             if os.path.exists(dtm_dir):
                 tifs = []
                 for root, dirs, files in os.walk(dtm_dir):
                     for f in files:
                         if f.lower().endswith(".tif") and not f.startswith("."):
                             tifs.append(os.path.join(root, f))
                 
                 if tifs:
                     dtm_path = tifs[0]
                     self.log(f"Trovati {len(tifs)} tiles. Uso {os.path.basename(dtm_path)} per statistiche.")
        
        if dtm_path and os.path.exists(dtm_path):
            try:
                res = processing.run("native:rasterlayerstatistics", {
                    'INPUT': dtm_path, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                max_dtm_z = res.get('MAX', res.get('MAXIMUM', max_dtm_z))
            except Exception as e:
                self.log(f"Impossibile leggere statistiche DTM: {str(e)}", Qgis.Warning)

        # Prerequisites rules:
        # - Lateral boundary: 0.5 * max height of structures
        # - Vertical extent: 2 * (max_elev + max_height)
        lateral_margin = max_bld_h * 0.5
        suggested_z = (max_dtm_z + max_bld_h) * 2.0
        
        # Cap vertical height at 2500m
        suggested_z = min(suggested_z, 2500.0)
        
        return lateral_margin, suggested_z, max_bld_h, max_dtm_z

    def _process_osm_roads(self, extent, target_crs, custom_widths=None, custom_materials=None):
        """Loads OSM roads, buffers them, and returns a road layer (memory)."""
        from .constants import ROAD_WIDTH_MAPPING, ROAD_MATERIAL_MAPPING
        
        if isinstance(target_crs, str):
            target_crs = QgsCoordinateReferenceSystem(target_crs)
            
        widths = custom_widths if custom_widths else ROAD_WIDTH_MAPPING
        materials = custom_materials if custom_materials else ROAD_MATERIAL_MAPPING
        
        project_dir = os.path.dirname(QgsProject.instance().fileName()) if QgsProject.instance().fileName() else None
        if not project_dir:
             project_dir = os.getcwd()

        project_name = os.path.splitext(os.path.basename(QgsProject.instance().fileName()))[0] if QgsProject.instance().fileName() else "default"
        roads_path = os.path.join(project_dir, f"EnviProtocol+{project_name}", "osm_roads", "roads.geojson")
        
        if not os.path.exists(roads_path):
            for root, dirs, files in os.walk(project_dir):
                if "roads.geojson" in files:
                    roads_path = os.path.join(root, "roads.geojson")
                    break
        
        if not os.path.exists(roads_path):
            self.log("Strade OSM non trovate, salto l'integrazione stradale.", Qgis.Info)
            return None

        road_layer = QgsVectorLayer(roads_path, "osm_roads", "ogr")
        if not road_layer.isValid():
            return None

        # Create a memory layer for buffered roads
        uri = f"MultiPolygon?crs={target_crs.authid()}&field=ENVI_ID:string(20)&field=Name:string(100)&field=DN:integer"
        mem_layer = QgsVectorLayer(uri, "buffered_roads", "memory")
        mem_layer.startEditing()
        
        source_crs = road_layer.crs()
        xf = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
        
        new_feats = []
        for feat in road_layer.getFeatures():
            geom = feat.geometry()
            geom.transform(xf)
            
            if not geom.intersects(extent):
                continue
                
            h_type = feat.attribute("highway")
            width = widths.get(h_type, widths.get("default", 4.0))
            envi_id = materials.get(h_type, materials.get("default", "0200ST"))
            
            # Buffer is half-width
            poly_geom = geom.buffer(width / 2.0, 5)
            if poly_geom and not poly_geom.isEmpty():
                f = QgsFeature(mem_layer.fields())
                f.setGeometry(poly_geom)
                f.setAttribute("ENVI_ID", envi_id)
                f.setAttribute("Name", f"Road ({h_type})")
                f.setAttribute("DN", 50)
                new_feats.append(f)

        if not new_feats:
            return None

        mem_layer.addFeatures(new_feats)
        mem_layer.commitChanges()
        
        # Dissolve by ENVI_ID to optimize
        dissolve_res = processing.run("native:dissolve", {
            'INPUT': mem_layer, 'FIELD': ['ENVI_ID'], 'OUTPUT': 'TEMPORARY_OUTPUT'
        })
        
        return dissolve_res['OUTPUT']

    def vectorize_land_use(self, input_raster, output_path, extent, custom_mapping=None, road_widths=None, road_materials=None, road_layer=None, precise_geometry=None):
        """Vectorizes ESA raster and integrates custom road network, clipped to precise geometry."""
        try:
            mapping = custom_mapping if custom_mapping else ESA_ENVIMET_MAPPING
            
            # 1. Reproject extent to raster CRS to avoid PB disk space error
            raster_layer = QgsRasterLayer(input_raster, "temp_raster")
            raster_crs = raster_layer.crs()
            project_crs = QgsProject.instance().crs()
            
            x_extent = extent
            if raster_crs != project_crs:
                self.log(f"Reprojecting extent from {project_crs.authid()} to {raster_crs.authid()}")
                xf = QgsCoordinateTransform(project_crs, raster_crs, QgsProject.instance())
                x_extent = xf.transformBoundingBox(extent)
                self.log(f"New extent: {x_extent.toString()}")

            # 2. Clip raster first to study area (performance boost)
            clip_res = processing.run("gdal:cliprasterbyextent", {
                'INPUT': input_raster,
                'PROJWIN': x_extent,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            clipped_raster = clip_res['OUTPUT']

            # 3. Polygonize the clipped raster
            vec_res = processing.run("gdal:polygonize", {
                'INPUT': clipped_raster, 'BAND': 1, 'FIELD': 'DN', 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            
            # 4. Dissolve by DN to speed up processing
            dissolve_res = processing.run("native:dissolve", {
                'INPUT': vec_res['OUTPUT'], 'FIELD': ['DN'], 'OUTPUT': self._temp_gpkg()
            })
            
            output_layer = dissolve_res['OUTPUT']
            if isinstance(output_layer, str):
                layer = QgsVectorLayer(output_layer, "temp_vector", "ogr")
            else:
                layer = output_layer

            if not layer or not layer.isValid() or layer.featureCount() == 0:
                return False, "Impossibile vettorizzare Land Use ESA (area vuota?)."

            # --- 2. EARLY REPROJECTION TO METRIC ---
            if layer.crs().authid() != project_crs.authid():
                self.log(f"Riproiezione Land Use da {layer.crs().authid()} a {project_crs.authid()}...")
                reproj_res = processing.run("native:reprojectlayer", {
                    'INPUT': layer, 'TARGET_CRS': project_crs.authid(), 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                layer = reproj_res['OUTPUT']

            # 3. Add ENVI_ID, Name and Map Values
            layer.startEditing()
            # Modern QgsField syntax: name, type
            layer.addAttribute(QgsField("ENVI_ID", QMetaType.QString, "string"))
            layer.addAttribute(QgsField("Name", QMetaType.QString, "string"))
            layer.updateFields()
            
            idx_dn = layer.fields().indexFromName("DN")
            idx_envi = layer.fields().indexFromName("ENVI_ID")
            idx_name = layer.fields().indexFromName("Name")
            
            for feat in layer.getFeatures():
                dn = feat.attributes()[idx_dn]
                
                # Use mapping (custom or default)
                envi_id = mapping.get(dn, "0200SL") 
                name = self._soil_names.get(envi_id, "Unknown Soil")
                
                layer.changeAttributeValue(feat.id(), idx_envi, envi_id) # FIXED: added missing field update
                layer.changeAttributeValue(feat.id(), idx_name, name)
            
            # --- 4. ROAD INTEGRATION (Customized) ---
            if not road_layer:
                self.log("Generazione layer stradale...")
                road_layer = self._process_osm_roads(extent, project_crs, road_widths, road_materials)
            
            if road_layer:
                # Difference: Land Use - Roads (cutholes)
                diff_res = processing.run("native:difference", {
                    'INPUT': layer, 'OVERLAY': road_layer, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                layer = diff_res['OUTPUT']
                
                # Merge: (Land Use - Roads) + Roads
                merge_res = processing.run("native:mergevectorlayers", {
                    'LAYERS': [layer, road_layer], 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                layer = merge_res['OUTPUT']
                
                # Re-tag names for the merged road features
                layer.startEditing()
                for f in layer.getFeatures():
                    eid = f.attribute("ENVI_ID")
                    if eid and not f.attribute("Name"):
                        layer.changeAttributeValue(f.id(), layer.fields().indexFromName("Name"), 
                                                self._soil_names.get(eid, "Road/Surface"))
            
            layer.commitChanges()
            
            # --- 5. FINAL CLIPPING TO PRECISE GEOMETRY ---
            if precise_geometry:
                self.log("Clipping finale Land Use alla Sub Area precisa...")
                # Create memory layer for precise geometry
                mask_layer = QgsVectorLayer(f"Polygon?crs={project_crs.authid()}", "mask", "memory")
                mask_layer.startEditing()
                f = QgsFeature()
                f.setGeometry(precise_geometry)
                mask_layer.addFeature(f)
                mask_layer.commitChanges()
                
                clip_res = processing.run("native:clip", {
                    'INPUT': layer, 'OVERLAY': mask_layer, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                layer = clip_res['OUTPUT']

            # 6. Save final 
            # Output is already in project_crs, just write to disk
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, output_path, QgsProject.instance().transformContext(), options
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                return False, f"Errore nel salvataggio finale: {error[1]}"
            
            self.log(f"Superfici salvate: {output_path}")
            return True, output_path
        except Exception as e:
            return False, str(e)

    def prepare_sub_area(self, extent, crs_auth_id, output_path, margin=0.0, geometry=None, name="", width=0.0, height=0.0, rotation=0.0, grid_size=0.0, color=""):
        """Creates a Sub Area layer from an extent/margin or specific geometry."""
        try:
            target_crs = QgsCoordinateReferenceSystem(crs_auth_id)
            if not target_crs.isValid():
                target_crs = QgsProject.instance().crs()
            
            if geometry:
                polygon = geometry
            else:
                # Apply margin to extent
                final_extent = QgsRectangle(extent)
                if margin > 0:
                    final_extent.grow(margin)
                polygon = QgsGeometry.fromRect(final_extent)
            
            # Set up fields
            fields = QgsFields()
            fields.append(QgsField("name", QMetaType.QString, "string", 255))
            fields.append(QgsField("width", QMetaType.Double, "double"))
            fields.append(QgsField("height", QMetaType.Double, "double"))
            fields.append(QgsField("rotation", QMetaType.Double, "double"))
            fields.append(QgsField("grid_size", QMetaType.Double, "double"))
            fields.append(QgsField("color", QMetaType.QString, "string", 50))
            
            # Thread safety check
            import threading
            is_main_thread = threading.current_thread() == threading.main_thread()
            
            if is_main_thread:
                # Try to edit in place if the layer is loaded in QGIS project
                project = QgsProject.instance()
                active_layer = None
                for lyr in project.mapLayers().values():
                    if lyr.source() == output_path:
                        active_layer = lyr
                        break
                
                if active_layer and active_layer.isValid():
                    active_layer.startEditing()
                    
                    # Delete all existing features
                    fids = [f.id() for f in active_layer.getFeatures()]
                    active_layer.deleteFeatures(fids)
                    
                    # Ensure fields exist
                    lyr_fields = active_layer.fields()
                    for field in fields:
                        if lyr_fields.indexFromName(field.name()) == -1:
                            active_layer.addAttribute(field)
                    active_layer.updateFields()
                    
                    feat = QgsFeature(active_layer.fields())
                    feat.setGeometry(polygon)
                    feat.setAttribute("name", name)
                    feat.setAttribute("width", width)
                    feat.setAttribute("height", height)
                    feat.setAttribute("rotation", rotation)
                    feat.setAttribute("grid_size", grid_size)
                    feat.setAttribute("color", color)
                    active_layer.addFeature(feat)
                    
                    if active_layer.commitChanges():
                        active_layer.dataProvider().reloadData()
                        active_layer.triggerRepaint()
                        self.log(f"Sub Area modificata in-place nel progetto: {output_path}")
                        return True, output_path
                    else:
                        active_layer.rollBack()
                        self.log(f"Modifica in-place fallita, provo a ricreare il file: {output_path}", Qgis.Warning)
            
            # Try to delete the file if it exists
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception as e:
                    # Deleting failed (likely locked)
                    if is_main_thread:
                        # In the main thread, try to load it temporarily to edit in-place
                        temp_layer = QgsVectorLayer(output_path, "temp_sub", "ogr")
                        if temp_layer.isValid():
                            temp_layer.startEditing()
                            fids = [f.id() for f in temp_layer.getFeatures()]
                            temp_layer.deleteFeatures(fids)
                            lyr_fields = temp_layer.fields()
                            for field in fields:
                                if lyr_fields.indexFromName(field.name()) == -1:
                                    temp_layer.addAttribute(field)
                            temp_layer.updateFields()
                            
                            feat = QgsFeature(temp_layer.fields())
                            feat.setGeometry(polygon)
                            feat.setAttribute("name", name)
                            feat.setAttribute("width", width)
                            feat.setAttribute("height", height)
                            feat.setAttribute("rotation", rotation)
                            feat.setAttribute("grid_size", grid_size)
                            feat.setAttribute("color", color)
                            temp_layer.addFeature(feat)
                            
                            if temp_layer.commitChanges():
                                del temp_layer
                                import gc
                                gc.collect()
                                self.log(f"Sub Area modificata in-place su disco (temp_layer): {output_path}")
                                return True, output_path
                            else:
                                temp_layer.rollBack()
                    else:
                        # In a background thread: if locked but valid, return success
                        self.log(f"File bloccato in thread secondario: {output_path}. Verifica validita'...", Qgis.Info)
                        try:
                            import sqlite3
                            conn = sqlite3.connect(output_path)
                            cursor = conn.cursor()
                            cursor.execute("SELECT table_name FROM gpkg_contents LIMIT 1")
                            row = cursor.fetchone()
                            if row:
                                table_name = row[0]
                                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                                count = cursor.fetchone()[0]
                                conn.close()
                                if count > 0:
                                    self.log(f"File sub-area valido trovato su disco ed e' bloccato. Salto ricreazione.", Qgis.Info)
                                    return True, output_path
                            conn.close()
                        except Exception as sqle:
                            self.log(f"Errore controllo sqlite del file bloccato: {sqle}", Qgis.Warning)
                    
                    return False, f"Il file e' bloccato da un altro processo o da QGIS ed e' impossibile sovrascriverlo: {str(e)}"
            
            # File deleted successfully or didn't exist: write new file
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
            
            writer = QgsVectorFileWriter.create(
                output_path,
                fields,
                QgsWkbTypes.Polygon,
                target_crs,
                QgsProject.instance().transformContext(),
                options
            )
            
            if writer.hasError() != QgsVectorFileWriter.NoError:
                return False, f"Errore creazione file: {writer.errorMessage()}"
            
            feat = QgsFeature(fields)
            feat.setGeometry(polygon)
            feat.setAttribute("name", name)
            feat.setAttribute("width", width)
            feat.setAttribute("height", height)
            feat.setAttribute("rotation", rotation)
            feat.setAttribute("grid_size", grid_size)
            feat.setAttribute("color", color)
            writer.addFeature(feat)
            
            del writer # Close file
            return True, output_path
        except Exception as e:
            return False, str(e)

    def process_buildings(self, input_path, output_path, aoi_geometry, crs_auth_id, building_settings=None):
        """Clips buildings to AOI and adds ENVI-met material/greening IDs."""
        from .constants import (
            BUILDING_WALL_MATERIAL_DEFAULT, BUILDING_ROOF_MATERIAL_DEFAULT,
            BUILDING_WALL_GREENING_DEFAULT, BUILDING_ROOF_GREENING_DEFAULT
        )
        
        if not os.path.exists(input_path):
            return False, "Layer edifici non trovato."

        # Use settings or defaults
        wall_id = building_settings.get("wall_id", BUILDING_WALL_MATERIAL_DEFAULT) if building_settings else BUILDING_WALL_MATERIAL_DEFAULT
        roof_id = building_settings.get("roof_id", BUILDING_ROOF_MATERIAL_DEFAULT) if building_settings else BUILDING_ROOF_MATERIAL_DEFAULT
        w_green_id = building_settings.get("wall_green_id", BUILDING_WALL_GREENING_DEFAULT) if building_settings else BUILDING_WALL_GREENING_DEFAULT
        r_green_id = building_settings.get("roof_green_id", BUILDING_ROOF_GREENING_DEFAULT) if building_settings else BUILDING_ROOF_GREENING_DEFAULT

        try:
            # 1. Create a temporary layer for the AOI geometry to use as OVERLAY
            aoi_layer = QgsVectorLayer(f"Polygon?crs={crs_auth_id}", "aoi_mask", "memory")
            aoi_layer.startEditing()
            f = QgsFeature()
            f.setGeometry(aoi_geometry)
            aoi_layer.addFeature(f)
            aoi_layer.commitChanges()

            # 2. Clip buildings using processing
            params = {
                'INPUT': input_path,
                'OVERLAY': aoi_layer,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
            res = processing.run("native:clip", params)
            clip_layer = res['OUTPUT']

            if not clip_layer or clip_layer.featureCount() == 0:
                return False, "Nessun edificio nell'area di studio."

            # 3. Add ENVI-met attributes
            clip_layer.startEditing()
            clip_layer.addAttribute(QgsField("ENVI_ID", QMetaType.QString, "string"))
            clip_layer.addAttribute(QgsField("ROOF_ID", QMetaType.QString, "string"))
            clip_layer.addAttribute(QgsField("W_GREEN_ID", QMetaType.QString, "string"))
            clip_layer.addAttribute(QgsField("R_GREEN_ID", QMetaType.QString, "string"))
            clip_layer.updateFields()
            
            idx_envi = clip_layer.fields().indexFromName("ENVI_ID")
            idx_roof = clip_layer.fields().indexFromName("ROOF_ID")
            idx_w_green = clip_layer.fields().indexFromName("W_GREEN_ID")
            idx_r_green = clip_layer.fields().indexFromName("R_GREEN_ID")

            for feat in clip_layer.getFeatures():
                attrs = {
                    idx_envi: wall_id,
                    idx_roof: roof_id,
                    idx_w_green: w_green_id,
                    idx_r_green: r_green_id
                }
                clip_layer.changeAttributeValues(feat.id(), attrs)
            clip_layer.commitChanges()

            # --- 4. FORCED REPROJECTION TO TARGET CRS ---
            target_crs = QgsCoordinateReferenceSystem(crs_auth_id)
            if clip_layer.crs().authid() != target_crs.authid():
                self.log(f"Reprojecting buildings from {clip_layer.crs().authid()} to {crs_auth_id}...")
                reproj_res = processing.run("native:reprojectlayer", {
                    'INPUT': clip_layer,
                    'TARGET_CRS': target_crs,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                clip_layer = reproj_res['OUTPUT']

            # 5. Save using explicit writer factory
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                clip_layer, 
                output_path, 
                QgsProject.instance().transformContext(), 
                options
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                return False, f"Errore salvataggio edifici: {error[1]}"
                
            return True, output_path
        except Exception as e:
            return False, str(e)

    def process_dtm(self, project_dir, output_path, extent, crs_auth_id, precise_geometry=None):
        """Combines and clips Tinitaly DTM tiles to a single GeoTIFF."""
        from .constants import FolderNames, FileNames
        dtm_dir = os.path.join(project_dir, FolderNames.TINITALY)
        if not os.path.exists(dtm_dir):
            return False, f"Cartella DTM non trovata in: {dtm_dir}"

        # 1. Recursive search for .tif files (in case they are in subdirectories)
        tifs = []
        for root, dirs, files in os.walk(dtm_dir):
            for f in files:
                if f.lower().endswith(".tif") and not f.startswith("."):
                    tifs.append(os.path.join(root, f))
        
        self.log(f"DTM Search in {dtm_dir}: trovati {len(tifs)} file.")
        
        if not tifs:
            return False, f"Nessun tile DTM (.tif) trovato in {dtm_dir} (anche sottocartelle)."

        try:
            # 2. Merge tiles if more than one
            if len(tifs) > 1:
                merge_params = {
                    'INPUT': tifs,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                }
                res = processing.run("gdal:merge", merge_params)
                merged = res['OUTPUT']
            else:
                merged = tifs[0]

            # 3. Reproject extent to DTM CRS
            raster_layer = QgsRasterLayer(merged, "temp_dtm")
            raster_crs = raster_layer.crs()
            project_crs = QgsProject.instance().crs()
            
            x_extent = extent
            if raster_crs.authid() != project_crs.authid():
                xf = QgsCoordinateTransform(project_crs, raster_crs, QgsProject.instance())
                x_extent = xf.transformBoundingBox(extent)

            # 4. Clip to extent
            temp_clip = output_path.replace(".tif", "_tmp_clip.tif")
            clip_params = {
                'INPUT': merged,
                'PROJWIN': x_extent,
                'NODATA': -9999,
                'OPTIONS': 'COMPRESS=LZW',
                'DATA_TYPE': 5, # Float32
                'OUTPUT': temp_clip
            }
            processing.run("gdal:cliprasterbyextent", clip_params)
            
            # --- 5. FORCED REPROJECTION TO TARGET CRS ---
            target_crs = QgsCoordinateReferenceSystem(crs_auth_id)
            # Since temp_clip was clipped from merged directly without reprojection,
            # it has the exact same CRS as raster_crs (the CRS of merged).
            if raster_crs.authid() != target_crs.authid():
                self.log(f"Reprojecting DTM from {raster_crs.authid()} to {crs_auth_id}...")
                warp_params = {
                    'INPUT': temp_clip,
                    'TARGET_CRS': crs_auth_id,
                    'RESAMPLING': 0, # Nearest Neighbour
                    'NODATA': -9999,
                    'DATA_TYPE': 5,
                    'OUTPUT': output_path
                }
                processing.run("gdal:warpreproject", warp_params)
                if os.path.exists(temp_clip):
                    try:
                        os.remove(temp_clip)
                    except Exception as e:
                        self.log(f"Non è stato possibile eliminare il file temporaneo DTM {temp_clip}: {e}", Qgis.Warning)
            else:
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except Exception as e:
                        self.log(f"Non è stato possibile eliminare il vecchio DTM {output_path}: {e}", Qgis.Warning)
                try:
                    os.rename(temp_clip, output_path)
                except Exception as e:
                    self.log(f"Errore nello spostamento del file DTM: {e}", Qgis.Warning)

            # --- 6. OPTIONAL FINAL CLIP TO PRECISE GEOMETRY ---
            if precise_geometry:
                self.log("Clipping finale DTM alla geometria precisa (ruotata)...")
                mask_layer = QgsVectorLayer(f"Polygon?crs={crs_auth_id}", "mask", "memory")
                mask_layer.startEditing()
                f = QgsFeature()
                f.setGeometry(precise_geometry)
                mask_layer.addFeature(f)
                mask_layer.commitChanges()

                final_clip = output_path.replace(".tif", "_final_mask.tif")
                mask_params = {
                    'INPUT': output_path,
                    'MASK': mask_layer,
                    'NODATA': -9999,
                    'ALPHA_BAND': False,
                    'CROP_TO_CUTLINE': True,
                    'KEEP_RESOLUTION': True,
                    'OPTIONS': 'COMPRESS=LZW',
                    'DATA_TYPE': 5,
                    'OUTPUT': final_clip
                }
                processing.run("gdal:cliprasterbymasklayer", mask_params)
                
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except Exception as e:
                        pass
                try:
                    os.rename(final_clip, output_path)
                except Exception as e:
                    self.log(f"Errore nello spostamento del DTM mascherato: {e}", Qgis.Warning)

            return True, output_path
        except Exception as e:
            return False, str(e)

    def process_vegetation_advanced(self, tcd_raster, eth_raster, output_path, aoi_geometry, extent, crs_auth_id, 
                                   tree_settings=None, buildings_layer=None, roads_layer=None, esa_raster=None):
        """Generates random tree points based on Tree Cover Density (TCD) and ETH height, with spatial cleaning."""
        if not os.path.exists(tcd_raster) or not os.path.exists(eth_raster):
            return False, "Dati TCD o ETH mancanti."

        # Tree settings defaults
        if not tree_settings:
            tree_settings = {
                "type": "Deciduous Trees",
                "density_mode": "auto", # auto, dense, sparse
                "tcd_threshold": 70,
                "exclude_barren_water": True,
                "exclude_grassland": True
            }

        try:
            # 1. Reproject extent to TCD CRS
            raster_layer = QgsRasterLayer(tcd_raster, "temp_tcd")
            raster_crs = raster_layer.crs()
            project_crs = QgsProject.instance().crs()
            
            x_extent = extent
            target_crs_obj = QgsCoordinateReferenceSystem(crs_auth_id)
            if raster_crs.authid() != target_crs_obj.authid():
                xf = QgsCoordinateTransform(project_crs, raster_crs, QgsProject.instance())
                x_extent = xf.transformBoundingBox(extent)

            # 2. Clip TCD to extent for speed
            self.log("Ritaglio del raster TCD all'estensione dell'area di studio...")
            clip_res = processing.run("gdal:cliprasterbyextent", {
                'INPUT': tcd_raster,
                'PROJWIN': x_extent,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_clipped = clip_res['OUTPUT']

            # 3. Clip ETH to extent for speed
            self.log("Ritaglio del raster ETH all'estensione dell'area di studio...")
            eth_qgs = QgsRasterLayer(eth_raster, "temp_eth")
            x_extent_eth = extent
            if eth_qgs.isValid():
                if eth_qgs.crs().authid() != project_crs.authid():
                    xf_e = QgsCoordinateTransform(project_crs, eth_qgs.crs(), QgsProject.instance())
                    x_extent_eth = xf_e.transformBoundingBox(extent)
            
            clip_eth_res = processing.run("gdal:cliprasterbyextent", {
                'INPUT': eth_raster, 'PROJWIN': x_extent_eth, 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            eth_clipped_path = clip_eth_res['OUTPUT']

            # 3.5 Clip and Warp ESA land use if requested for filtering
            esa_warped = None
            esa_clipped_path = None
            exclude_barren_water = tree_settings.get("exclude_barren_water", True) if tree_settings else True
            exclude_grassland = tree_settings.get("exclude_grassland", True) if tree_settings else True
            
            if (exclude_barren_water or exclude_grassland) and esa_raster and os.path.exists(esa_raster):
                self.log("Ritaglio del raster Land Use ESA per il filtraggio vegetazione...")
                esa_qgs = QgsRasterLayer(esa_raster, "temp_esa")
                x_extent_esa = extent
                if esa_qgs.isValid():
                    if esa_qgs.crs().authid() != project_crs.authid():
                        xf_esa = QgsCoordinateTransform(project_crs, esa_qgs.crs(), QgsProject.instance())
                        x_extent_esa = xf_esa.transformBoundingBox(extent)
                
                clip_esa_res = processing.run("gdal:cliprasterbyextent", {
                    'INPUT': esa_raster, 'PROJWIN': x_extent_esa, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                esa_clipped_path = clip_esa_res['OUTPUT']
                
                esa_rl = QgsRasterLayer(esa_clipped_path, "esa_clipped")
                if esa_rl.crs().authid() != target_crs_obj.authid():
                    esa_warped = os.path.join(os.path.dirname(output_path), "esa_warped_tmp.tif")
                    processing.run("gdal:warpreproject", {
                        'INPUT': esa_clipped_path,
                        'TARGET_CRS': crs_auth_id,
                        'RESAMPLING': 0, # Nearest Neighbour
                        'NODATA': -9999,
                        'OUTPUT': esa_warped
                    })
                else:
                    esa_warped = esa_clipped_path

            # 4. Warp clipped rasters to the target CRS (metric) if needed
            self.log("Allineamento e riproiezione dei raster al CRS di destinazione...")
            
            tcd_rl = QgsRasterLayer(tcd_clipped, "tcd_clipped")
            if tcd_rl.crs().authid() != target_crs_obj.authid():
                tcd_warped = os.path.join(os.path.dirname(output_path), "tcd_warped_tmp.tif")
                processing.run("gdal:warpreproject", {
                    'INPUT': tcd_clipped,
                    'TARGET_CRS': crs_auth_id,
                    'RESAMPLING': 0, # Nearest Neighbour
                    'NODATA': -9999,
                    'OUTPUT': tcd_warped
                })
            else:
                tcd_warped = tcd_clipped

            eth_rl = QgsRasterLayer(eth_clipped_path, "eth_clipped")
            if eth_rl.crs().authid() != target_crs_obj.authid():
                eth_warped = os.path.join(os.path.dirname(output_path), "eth_warped_tmp.tif")
                processing.run("gdal:warpreproject", {
                    'INPUT': eth_clipped_path,
                    'TARGET_CRS': crs_auth_id,
                    'RESAMPLING': 0, # Nearest Neighbour
                    'NODATA': -9999,
                    'OUTPUT': eth_warped
                })
            else:
                eth_warped = eth_clipped_path

            # 5. Convert pixels to points (very fast, automatically skips NoData pixels)
            self.log("Conversione dei pixel TCD in punti vettoriali...")
            tcd_pts_res = processing.run("native:pixelstopoints", {
                'INPUT_RASTER': tcd_warped,
                'RASTER_BAND': 1,
                'FIELD_NAME': 'tcd_val',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_pts = tcd_pts_res['OUTPUT']

            self.log("Conversione dei pixel ETH in punti vettoriali...")
            eth_pts_res = processing.run("native:pixelstopoints", {
                'INPUT_RASTER': eth_warped,
                'RASTER_BAND': 1,
                'FIELD_NAME': 'eth_val',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            eth_pts = eth_pts_res['OUTPUT']

            # 5.5 Pre-filter points in C++ using extractbyexpression
            d_mult = tree_settings.get("density_multiplier", 1.0) if tree_settings else 1.0

            self.log("Filtraggio punti TCD in C++...")
            tcd_filtered_res = processing.run("native:extractbyexpression", {
                'INPUT': tcd_pts,
                'EXPRESSION': '"tcd_val" >= 10 AND "tcd_val" <= 100',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_filtered = tcd_filtered_res['OUTPUT']

            self.log("Filtraggio punti ETH in C++...")
            eth_filtered_res = processing.run("native:extractbyexpression", {
                'INPUT': eth_pts,
                'EXPRESSION': '"eth_val" >= 2',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            eth_filtered = eth_filtered_res['OUTPUT']

            # 5.6 Spatial cleaning in C++ (Extract by location disjoint from buildings/roads)
            def ensure_spatial_index(layer_input):
                if layer_input:
                    try:
                        processing.run("native:createspatialindex", {'INPUT': layer_input})
                    except Exception as e:
                        self.log(f"Avviso creazione indice spaziale: {e}", Qgis.Warning)

            ensure_spatial_index(buildings_layer)
            ensure_spatial_index(roads_layer)

            if buildings_layer and buildings_layer.isValid() and buildings_layer.featureCount() > 0:
                self.log("Rimozione punti TCD sovrapposti a edifici in C++...")
                ensure_spatial_index(tcd_filtered)
                tcd_filtered_res = processing.run("native:extractbylocation", {
                    'INPUT': tcd_filtered,
                    'PREDICATE': [2], # disjoint
                    'INTERSECT': buildings_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                tcd_filtered = tcd_filtered_res['OUTPUT']

                self.log("Rimozione punti ETH sovrapposti a edifici in C++...")
                ensure_spatial_index(eth_filtered)
                eth_filtered_res = processing.run("native:extractbylocation", {
                    'INPUT': eth_filtered,
                    'PREDICATE': [2], # disjoint
                    'INTERSECT': buildings_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                eth_filtered = eth_filtered_res['OUTPUT']

            if roads_layer and roads_layer.isValid() and roads_layer.featureCount() > 0:
                self.log("Rimozione punti TCD sovrapposti a strade in C++...")
                ensure_spatial_index(tcd_filtered)
                tcd_filtered_res = processing.run("native:extractbylocation", {
                    'INPUT': tcd_filtered,
                    'PREDICATE': [2], # disjoint
                    'INTERSECT': roads_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                tcd_filtered = tcd_filtered_res['OUTPUT']

                self.log("Rimozione punti ETH sovrapposti a strade in C++...")
                ensure_spatial_index(eth_filtered)
                eth_filtered_res = processing.run("native:extractbylocation", {
                    'INPUT': eth_filtered,
                    'PREDICATE': [2], # disjoint
                    'INTERSECT': roads_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                eth_filtered = eth_filtered_res['OUTPUT']

            # 6. Sample rasters on the filtered points to get the missing variable
            self.log("Campionamento altezze sui punti TCD pre-filtrati...")
            sample_eth_res = processing.run("native:rastersampling", {
                'INPUT': tcd_filtered,
                'RASTERCOPY': eth_warped,
                'COLUMN_PREFIX': 'height_',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_sampled = sample_eth_res['OUTPUT']
            if isinstance(tcd_sampled, str):
                tcd_sampled = QgsVectorLayer(tcd_sampled, "tcd_sampled", "ogr")

            if esa_warped:
                self.log("Campionamento Land Use ESA sui punti TCD pre-filtrati...")
                sample_esa_res = processing.run("native:rastersampling", {
                    'INPUT': tcd_sampled,
                    'RASTERCOPY': esa_warped,
                    'COLUMN_PREFIX': 'esa_',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                tcd_sampled = sample_esa_res['OUTPUT']
                if isinstance(tcd_sampled, str):
                    tcd_sampled = QgsVectorLayer(tcd_sampled, "tcd_sampled", "ogr")

            self.log("Campionamento densità sui punti ETH pre-filtrati...")
            sample_tcd_res = processing.run("native:rastersampling", {
                'INPUT': eth_filtered,
                'RASTERCOPY': tcd_warped,
                'COLUMN_PREFIX': 'tcd_',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            eth_sampled = sample_tcd_res['OUTPUT']
            if isinstance(eth_sampled, str):
                eth_sampled = QgsVectorLayer(eth_sampled, "eth_sampled", "ogr")

            if esa_warped:
                self.log("Campionamento Land Use ESA sui punti ETH pre-filtrati...")
                sample_esa_res_eth = processing.run("native:rastersampling", {
                    'INPUT': eth_sampled,
                    'RASTERCOPY': esa_warped,
                    'COLUMN_PREFIX': 'esa_',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                eth_sampled = sample_esa_res_eth['OUTPUT']
                if isinstance(eth_sampled, str):
                    eth_sampled = QgsVectorLayer(eth_sampled, "eth_sampled", "ogr")

            # 7. Initialize target fields and database lookups
            fields = QgsFields()
            fields.append(QgsField("ENVI_ID", QMetaType.QString, "string", 6))
            fields.append(QgsField("Name", QMetaType.QString, "string"))
            fields.append(QgsField("height_1", QMetaType.Double, "double"))
            fields.append(QgsField("tcd_1", QMetaType.Double, "double"))

            # Load species database
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "envimet_db.json")
            db_plants = {}
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                    db_plants = db.get("3d_plants", {}).get("Abstract", {})
            except Exception as e:
                self.log(f"Impossibile leggere database piante: {e}", Qgis.Warning)

            tree_type = tree_settings.get("type", "Deciduous Trees") if tree_settings else "Deciduous Trees"
            type_data = db_plants.get(tree_type, {})
            d_mode = tree_settings.get("density_mode", "auto") if tree_settings else "auto"
            t_thresh = tree_settings.get("tcd_threshold", 70) if tree_settings else 70
            pref_shape = tree_settings.get("shape", "Random") if tree_settings else "Random"

            def get_species_for_tree(h, tcd_val):
                if h is None or h < 2:
                    return "0000XX", "Unknown Tree"
                elif h < 10:
                    h_cat = "Small"
                elif h < 20:
                    h_cat = "Medium"
                else:
                    h_cat = "Large"

                if not type_data:
                    return "0000XX", "Unknown Tree"

                if d_mode == "auto":
                    c_density = "dense canopy" if (tcd_val and tcd_val >= t_thresh) else "sparse canopy"
                else:
                    c_density = f"{d_mode} canopy"

                size_data = type_data.get(h_cat, {})
                if isinstance(size_data, list):
                    plants = size_data
                else:
                    plants = size_data.get(c_density, size_data.get("dense canopy", []))

                if plants:
                    if pref_shape == "Random":
                        selected_plant = random.choice(plants)
                    elif pref_shape == "Palm":
                        selected_plant = plants[0]
                    else:
                        matches = [p for p in plants if pref_shape.lower() in p["name"].lower()]
                        if matches:
                            selected_plant = random.choice(matches)
                        else:
                            selected_plant = plants[0]
                    return selected_plant["envi_id"], selected_plant["name"]
                else:
                    return "0010MO", "Deciduous Tree Fallback"

            # Find dynamic field names in sampled layers
            f_names_tcd = [f.name() for f in tcd_sampled.fields()]
            idx_tcd_val = tcd_sampled.fields().indexFromName("tcd_val")
            idx_height_sampled = -1
            for target in ["height_1", "height", "height_1_1", "SAMPLE", "SAMPLE_1"]:
                if target in f_names_tcd:
                    idx_height_sampled = tcd_sampled.fields().indexFromName(target)
                    break

            idx_esa_tcd = -1
            if esa_warped:
                for target in ["esa_1", "esa", "esa_1_1", "SAMPLE", "SAMPLE_1"]:
                    if target in f_names_tcd:
                        idx = tcd_sampled.fields().indexFromName(target)
                        if idx != idx_height_sampled:
                            idx_esa_tcd = idx
                            break

            f_names_eth = [f.name() for f in eth_sampled.fields()]
            idx_eth_val = eth_sampled.fields().indexFromName("eth_val")
            idx_tcd_sampled = -1
            for target in ["tcd_1", "tcd", "tcd_1_1", "SAMPLE", "SAMPLE_1"]:
                if target in f_names_eth:
                    idx_tcd_sampled = eth_sampled.fields().indexFromName(target)
                    break

            idx_esa_eth = -1
            if esa_warped:
                for target in ["esa_1", "esa", "esa_1_1", "SAMPLE", "SAMPLE_1"]:
                    if target in f_names_eth:
                        idx = eth_sampled.fields().indexFromName(target)
                        if idx != idx_tcd_sampled:
                            idx_esa_eth = idx
                            break

            new_features = []
            next_id = 1

            # Prepare the rapid boundary check rectangle (grow original extent by suggested margin)
            margin = 0.0
            if aoi_geometry:
                aoi_bbox = aoi_geometry.boundingBox()
                margin = (aoi_bbox.width() - extent.width()) * 0.5
                margin = max(margin, 0.0)
            
            aoi_rect = QgsRectangle(extent)
            if margin > 0.0:
                aoi_rect.grow(margin)

            # 8. Loop over final TCD points
            self.log("Posizionamento finale e jittering punti vegetazione TCD...")
            for feat in tcd_sampled.getFeatures():
                # Check ESA Land Use to exclude barren/water/grassland
                if idx_esa_tcd != -1:
                    esa_val = feat.attributes()[idx_esa_tcd]
                    if esa_val is not None and not (isinstance(esa_val, QVariant) and esa_val.isNull()):
                        try:
                            val_int = int(float(esa_val))
                            if exclude_barren_water and val_int in [60, 70, 80]:
                                continue
                            if exclude_grassland and val_int == 30:
                                continue
                        except (ValueError, TypeError):
                            pass

                tcd_val = feat.attributes()[idx_tcd_val]
                if tcd_val is None or (isinstance(tcd_val, QVariant) and tcd_val.isNull()):
                    continue
                
                tcd_val = float(tcd_val)
                h = None
                if idx_height_sampled != -1:
                    h_val = feat.attributes()[idx_height_sampled]
                    if h_val is not None and not (isinstance(h_val, QVariant) and h_val.isNull()):
                        h = float(h_val)

                if h is None or h < 2.0:
                    continue

                # Calculate expected number of trees based on TCD and height
                # Canopy width = h * 0.7, so radius = h * 0.35
                r = h * 0.35
                a_tree = math.pi * (r ** 2)
                # target canopy area in a 10m x 10m cell (100 m2) is tcd_val (since tcd_val is in %)
                n_trees = (tcd_val / a_tree) * d_mult
                
                # Cap the number of trees per pixel to prevent performance issues
                n_trees = min(n_trees, 4.0)
                
                # Determine how many trees to place
                num_to_place = int(n_trees)
                remainder = n_trees - num_to_place
                if random.random() < remainder:
                    num_to_place += 1
                
                if num_to_place == 0:
                    continue

                # Lookup species
                envi_id, species_name = get_species_for_tree(h, tcd_val)
                if envi_id == "0000XX":
                    continue

                pt = feat.geometry().asPoint()
                
                for _ in range(num_to_place):
                    # Jitter coordinates within the 10m x 10m pixel cell boundaries ([-5, 5])
                    dx = random.uniform(-5.0, 5.0)
                    dy = random.uniform(-5.0, 5.0)
                    jittered_pt = QgsPointXY(pt.x() + dx, pt.y() + dy)

                    if not aoi_rect.contains(jittered_pt):
                        continue

                    # Create feature
                    new_f = QgsFeature(fields)
                    new_f.setGeometry(QgsGeometry.fromPointXY(jittered_pt))
                    new_f.setAttribute("ENVI_ID", envi_id)
                    new_f.setAttribute("Name", species_name)
                    new_f.setAttribute("height_1", h)
                    new_f.setAttribute("tcd_1", tcd_val)
                    new_f.setId(next_id)
                    next_id += 1
                    new_features.append(new_f)

            # 9. Loop over final ETH points
            self.log("Posizionamento finale e jittering punti vegetazione ETH di fallback...")
            for feat in eth_sampled.getFeatures():
                # Check ESA Land Use to exclude barren/water/grassland
                if idx_esa_eth != -1:
                    esa_val = feat.attributes()[idx_esa_eth]
                    if esa_val is not None and not (isinstance(esa_val, QVariant) and esa_val.isNull()):
                        try:
                            val_int = int(float(esa_val))
                            if exclude_barren_water and val_int in [60, 70, 80]:
                                continue
                            if exclude_grassland and val_int == 30:
                                continue
                        except (ValueError, TypeError):
                            pass

                h = feat.attributes()[idx_eth_val]
                if h is None or (isinstance(h, QVariant) and h.isNull()):
                    continue
                
                h = float(h)
                if h < 2.0:
                    continue

                tcd_val = 0.0
                if idx_tcd_sampled != -1:
                    tcd_val_raw = feat.attributes()[idx_tcd_sampled]
                    if tcd_val_raw is not None and not (isinstance(tcd_val_raw, QVariant) and tcd_val_raw.isNull()):
                        tcd_val = float(tcd_val_raw)

                if tcd_val >= 10.0:
                    continue # Already covered by TCD loop

                # Apply probabilistic filter for low density ETH fallback points
                prob = 0.50 * d_mult
                if random.random() > prob:
                    continue

                # Lookup species
                envi_id, species_name = get_species_for_tree(h, tcd_val)
                if envi_id == "0000XX":
                    continue

                # Jitter coordinates within the 10m x 10m pixel cell boundaries ([-5, 5])
                pt = feat.geometry().asPoint()
                dx = random.uniform(-5.0, 5.0)
                dy = random.uniform(-5.0, 5.0)
                jittered_pt = QgsPointXY(pt.x() + dx, pt.y() + dy)

                if not aoi_rect.contains(jittered_pt):
                    continue

                # Create feature
                new_f = QgsFeature(fields)
                new_f.setGeometry(QgsGeometry.fromPointXY(jittered_pt))
                new_f.setAttribute("ENVI_ID", envi_id)
                new_f.setAttribute("Name", species_name)
                new_f.setAttribute("height_1", h)
                new_f.setAttribute("tcd_1", tcd_val)
                new_f.setId(next_id)
                next_id += 1
                new_features.append(new_f)

            if not new_features:
                return False, "Nessun albero generato dai layer TCD e ETH."

            # 10. Save final Points layer
            self.log("Salvataggio dei punti vegetazione finali...")
            uri = f"Point?crs={crs_auth_id}&field=ENVI_ID:string(6)&field=Name:string(100)&field=height_1:double&field=tcd_1:double"
            mem_layer = QgsVectorLayer(uri, "final_veg", "memory")
            mem_layer.startEditing()
            mem_layer.addFeatures(new_features)
            mem_layer.commitChanges()

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer, 
                output_path, 
                QgsProject.instance().transformContext(), 
                options
            )
            
            # Cleanup temporary warped files
            for p in [tcd_warped, eth_warped, esa_warped]:
                if p and p not in (tcd_clipped, eth_clipped_path, esa_clipped_path) and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception as e:
                        self.log(f"Non è stato possibile eliminare il file temporaneo {p}: {e}", Qgis.Warning)

            if error[0] != QgsVectorFileWriter.NoError:
                return False, f"Errore creazione vegetazione: {error[1]}"
                
            return True, output_path

        except Exception as e:
            return False, str(e)

    def process_simple_plants(self, esa_raster, tcd_raster, output_path, extent, crs_auth_id, road_layer=None, custom_mapping=None, precise_geometry=None):
        """Extracts Simple Plant surfaces from ESA Land Use data and TCD tree undergrowth, cutting roads."""
        from .constants import ESA_SIMPLE_PLANT_MAPPING
        try:
            mapping = custom_mapping if custom_mapping else ESA_SIMPLE_PLANT_MAPPING
            
            # --- 1. PROCESS ESA (Shrubs, Grass, Crops) ---
            raster_layer = QgsRasterLayer(esa_raster, "temp_raster")
            raster_crs = raster_layer.crs()
            project_crs = QgsProject.instance().crs()
            
            x_extent = extent
            target_crs_obj = QgsCoordinateReferenceSystem(crs_auth_id)
            if raster_crs.authid() != target_crs_obj.authid():
                xf = QgsCoordinateTransform(project_crs, raster_crs, QgsProject.instance())
                x_extent = xf.transformBoundingBox(extent)

            clip_res = processing.run("gdal:cliprasterbyextent", {
                'INPUT': esa_raster, 'PROJWIN': x_extent, 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            vec_res = processing.run("gdal:polygonize", {
                'INPUT': clip_res['OUTPUT'], 'BAND': 1, 'FIELD': 'DN', 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            
            valid_dns = list(mapping.keys())
            # Clean valid_dns from non-integer keys (like TCD_UNDERgrowth)
            valid_dns = [dn for dn in valid_dns if isinstance(dn, int)]
            dns_str = ",".join([str(dn) for dn in valid_dns])
            
            filter_res = processing.run("native:extractbyexpression", {
                'INPUT': vec_res['OUTPUT'],
                'EXPRESSION': f'"DN" IN ({dns_str})',
                'OUTPUT': self._temp_gpkg()
            })
            
            esa_layer = filter_res['OUTPUT']
            if isinstance(esa_layer, str): esa_layer = QgsVectorLayer(esa_layer, "esa_p", "ogr")

            # Tag ESA IDs
            esa_layer.startEditing()
            esa_layer.addAttribute(QgsField("ENVI_ID", QMetaType.QString, "string"))
            esa_layer.addAttribute(QgsField("Name", QMetaType.QString, "string"))
            esa_layer.updateFields()
            idx_dn = esa_layer.fields().indexFromName("DN")
            idx_envi = esa_layer.fields().indexFromName("ENVI_ID")
            idx_name = esa_layer.fields().indexFromName("Name")
            for feat in esa_layer.getFeatures():
                dn = feat.attributes()[idx_dn]
                envi_id = mapping.get(dn, "0200XX")
                esa_layer.changeAttributeValue(feat.id(), idx_envi, envi_id)
                esa_layer.changeAttributeValue(feat.id(), idx_name, self._soil_names.get(envi_id, "Simple Plant"))
            esa_layer.commitChanges()

            # --- 2. PROCESS TCD (Undergrowth under 3D trees) ---
            tcd_layer = None
            if tcd_raster and os.path.exists(tcd_raster):
                tcd_rl = QgsRasterLayer(tcd_raster, "temp_tcd")
                tcd_crs = tcd_rl.crs()
                tx_extent = extent
                if tcd_crs != project_crs:
                    xf = QgsCoordinateTransform(project_crs, tcd_crs, QgsProject.instance())
                    tx_extent = xf.transformBoundingBox(extent)

                t_clip = processing.run("gdal:cliprasterbyextent", {
                    'INPUT': tcd_raster, 'PROJWIN': tx_extent, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                t_vec = processing.run("gdal:polygonize", {
                    'INPUT': t_clip['OUTPUT'], 'BAND': 1, 'FIELD': 'TCD', 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                t_filter = processing.run("native:extractbyexpression", {
                    'INPUT': t_vec['OUTPUT'],
                    'EXPRESSION': '"TCD" >= 10 AND "TCD" <= 100',
                    'OUTPUT': self._temp_gpkg()
                })
                tcd_layer = t_filter['OUTPUT']
                if isinstance(tcd_layer, str): tcd_layer = QgsVectorLayer(tcd_layer, "tcd_p", "ogr")
                
                # Tag TCD as Grass (using mapping if exists)
                tcd_layer.startEditing()
                tcd_layer.addAttribute(QgsField("ENVI_ID", QMetaType.QString, "string"))
                tcd_layer.addAttribute(QgsField("Name", QMetaType.QString, "string"))
                tcd_layer.updateFields()
                idx_envi_t = tcd_layer.fields().indexFromName("ENVI_ID")
                idx_name_t = tcd_layer.fields().indexFromName("Name")
                
                tcd_envi_id = mapping.get("TCD_UNDERgrowth", "0200XX")
                
                for feat in tcd_layer.getFeatures():
                    tcd_layer.changeAttributeValue(feat.id(), idx_envi_t, tcd_envi_id)
                    tcd_layer.changeAttributeValue(feat.id(), idx_name_t, self._soil_names.get(tcd_envi_id, "Undergrowth"))
                tcd_layer.commitChanges()

            # --- 3. MERGE, DISSOLVE AND CUT ROADS ---
            final_layer = esa_layer
            if tcd_layer and tcd_layer.featureCount() > 0:
                merge_res = processing.run("native:mergevectorlayers", {
                    'LAYERS': [esa_layer, tcd_layer], 'OUTPUT': self._temp_gpkg()
                })
                final_layer = merge_res['OUTPUT']
                if isinstance(final_layer, str): final_layer = QgsVectorLayer(final_layer, "merged", "ogr")

            # Dissolve by ENVI_ID
            diss_res = processing.run("native:dissolve", {
                'INPUT': final_layer, 'FIELD': ['ENVI_ID'], 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            final_layer = diss_res['OUTPUT']

            # --- 4. SUBTRACT ROADS ---
            if road_layer and final_layer:
                self.log("Sottrazione aree stradali da Simple Plants...")
                diff_res = processing.run("native:difference", {
                    'INPUT': final_layer, 'OVERLAY': road_layer, 'OUTPUT': self._temp_gpkg()
                })
                final_layer = diff_res['OUTPUT']
            
            # Remove null geometries that may result from difference operations
            if final_layer:
                clean_res = processing.run("native:removenullgeometries", {
                    'INPUT': final_layer, 'OUTPUT': self._temp_gpkg()
                })
                final_layer = clean_res['OUTPUT']

            if isinstance(final_layer, str): final_layer = QgsVectorLayer(final_layer, "final_veg", "ogr")

            # --- 4.5 FINAL CLIPPING TO PRECISE GEOMETRY ---
            if precise_geometry:
                self.log("Clipping finale Simple Plants alla Sub Area precisa...")
                mask_layer = QgsVectorLayer(f"Polygon?crs={project_crs.authid()}", "mask", "memory")
                mask_layer.startEditing()
                f = QgsFeature()
                f.setGeometry(precise_geometry)
                mask_layer.addFeature(f)
                mask_layer.commitChanges()
                
                clip_res = processing.run("native:clip", {
                    'INPUT': final_layer, 'OVERLAY': mask_layer, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                final_layer = clip_res['OUTPUT']

            # --- 5. Save final - FORCE REPROJECTION TO TARGET ---
            if final_layer.crs().authid() != target_crs_obj.authid():
                self.log(f"Riproiezione finale Simple Plants a {target_crs_obj.authid()}...")
                reproj_res = processing.run("native:reprojectlayer", {
                    'INPUT': final_layer,
                    'TARGET_CRS': target_crs_obj.authid(),
                    'OUTPUT': output_path
                })
                if os.path.exists(output_path):
                    return True, output_path
                else:
                    return False, "Errore nella riproiezione finale delle piante semplici."
            else:
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.fileEncoding = "UTF-8"
                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    final_layer, output_path, QgsProject.instance().transformContext(), options
                )
                if error[0] != QgsVectorFileWriter.NoError:
                    return False, f"Errore salvataggio Simple Plants: {error[1]}"
                
                return True, output_path
            
        except Exception as e:
            return False, str(e)

    def level_terrain_under_buildings(self, terrain_path, buildings_path):
        """
        Levels the DTM raster under building footprints by calculating the mean
        elevation for each building and updating the raster pixels.
        """
        if not os.path.exists(terrain_path) or not os.path.exists(buildings_path):
            self.log("Impossibile livellare: DTM o edifici mancanti.", Qgis.Warning)
            return False

        try:
            self.log(f"Inizio livellamento terreno sotto gli edifici...")
            
            # 1. Load the layer explicitly
            vlayer_src = QgsVectorLayer(buildings_path, "buildings_src", "ogr")
            rlayer = QgsRasterLayer(terrain_path, "terrain_tmp")
            
            if not vlayer_src or not vlayer_src.isValid():
                self.log(f"Impossibile caricare edifici: {buildings_path}", Qgis.Warning)
                return False
            if not rlayer or not rlayer.isValid():
                self.log(f"Impossibile caricare DTM: {terrain_path}", Qgis.Warning)
                return False

            # 2. Always create a memory layer copy to avoid file lock/modification issues
            # We also handle reprojection here if needed
            target_crs = rlayer.crs()
            self.log(f"Copia edifici in memoria (Target CRS: {target_crs.authid()})...")
            
            reproj_params = {
                'INPUT': vlayer_src,
                'TARGET_CRS': target_crs,
                'OUTPUT': self._temp_gpkg()
            }
            reproj_res = processing.run("native:reprojectlayer", reproj_params)
            vlayer = reproj_res['OUTPUT']
            
            if isinstance(vlayer, str):
                vlayer = QgsVectorLayer(vlayer, "bld_lev", "ogr")

            # 3. Calculate Mean Elevation
            # NOTE: native:zonalstatistics often modifies the layer IN-PLACE 
            # and does NOT return an 'OUTPUT' key in some QGIS versions.
            params = {
                'INPUT': vlayer,
                'INPUT_RASTER': rlayer,
                'RASTER_BAND': 1,
                'COLUMN_PREFIX': '_lev_',
                'STATISTICS': [2] # Mean
            }
            
            self.log("Calcolo statistiche zonali (media elevazione)...")
            try:
                processing.run("native:zonalstatistics", params)
            except Exception as e:
                self.log(f"Fallback su INPUT_VECTOR per zonalstats...")
                params.pop('INPUT', None)
                params['INPUT_VECTOR'] = vlayer
                processing.run("native:zonalstatistics", params)
            
            # Since it's in-place, vlayer now contains the '_lev_mean' field
            # 4. Rasterize the building pads
            self.log("Rasterizzazione piazzole edifici...")
            
            # Get extent and resolution from rlayer to be 100% compliant with new QGIS/GDAL providers
            ext = rlayer.extent()
            res_x = rlayer.rasterUnitsPerPixelX()
            res_y = rlayer.rasterUnitsPerPixelY()
            
            # gdal:rasterize in newer QGIS versions requires explicit UNITS, WIDTH/HEIGHT, and EXTENT
            pads_res = processing.run("gdal:rasterize", {
                'INPUT': vlayer,
                'FIELD': '_lev_mean',
                'UNITS': 1, # 1 corresponds to "Georeferenced units"
                'WIDTH': res_x,
                'HEIGHT': res_y,
                'EXTENT': ext,
                'OPTIONS': '',
                'DATA_TYPE': 5, # 5 is Float32
                'INIT': -9999,
                'NODATA': -9999,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            pads_raster = pads_res['OUTPUT']

            # 5. Combine original DTM and Building Pads
            self.log("Fusione DTM con piazzole livellate (Merge)...")
            temp_final = terrain_path.replace(".tif", "_leveled_tmp.tif")
            
            # Libera i lock su Windows cancellando i layer dalla memoria
            if 'rlayer' in locals(): del rlayer
            if 'vlayer' in locals(): del vlayer
            if 'vlayer_src' in locals(): del vlayer_src
            if 'params' in locals(): params.clear()

            # gdal:merge processes layers in order. Draw terrain first, then pads on top.
            # By setting NODATA_INPUT to -9999, the empty areas of pads won't wipe out the terrain.
            processing.run("gdal:merge", {
                'INPUT': [terrain_path, pads_raster],
                'PCT': False,
                'SEPARATE': False,
                'NODATA_INPUT': -9999,
                'NODATA_OUTPUT': -9999,
                'OPTIONS': '',
                'DATA_TYPE': 5, # Float32
                'OUTPUT': temp_final
            })
            
            if os.path.exists(temp_final):
                if os.path.exists(terrain_path):
                    try:
                        os.remove(terrain_path)
                    except PermissionError:
                        import time
                        time.sleep(1) # wait for gdal/qgis to fully release handles
                        os.remove(terrain_path)
                os.rename(temp_final, terrain_path)
                self.log("Livellamento terreno completato con successo.")
                return True
            
            return False
        except Exception as e:
            self.log(f"Errore critico livellamento: {str(e)}", Qgis.Warning)
            import traceback
            self.log(traceback.format_exc(), Qgis.Warning)
            return False

    def process_vegetation(self, esa_raster, eth_raster, output_path):
        """Legacy placeholder replaced by process_vegetation_advanced."""
        return True, "Usare process_vegetation_advanced"

    def migrate_project_to_target_crs(self, target_crs_auth, task=None):
        """
        Scans the project directory and reprojects all prepared layers to the target CRS.
        Useful when changing between coordinate systems (e.g. 3003/3004 to UTM).
        """
        from .utils import get_target_crs_for_extent
        
        project = QgsProject.instance()
        project_path = project.fileName()
        if not project_path:
            return False, "Progetto non salvato. Salva il progetto prima di migrare i dati."

        project_dir = os.path.dirname(project_path)
        project_name = os.path.splitext(os.path.basename(project_path))[0]
        data_dir = os.path.join(project_dir, f"EnviProtocol+{project_name}")

        if not os.path.exists(data_dir):
            return False, f"Cartella dati non trovata: {data_dir}"

        target_crs = QgsCoordinateReferenceSystem(target_crs_auth)
        if not target_crs.isValid():
            return False, "CRS di destinazione non valido."

        self.log(f"Avvio migrazione dati verso {target_crs_auth} in {data_dir}...")
        
        count = 0
        errors = []

        # Pre-collect matching files to track progress percentage
        matching_files = []
        for root, dirs, files in os.walk(data_dir):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in ['.gpkg', '.tif', '.tiff', '.geojson', '.shp']:
                    matching_files.append((root, filename))

        total_files = len(matching_files)
        if total_files == 0:
            return True, "Nessun file da migrare."

        for i, (root, filename) in enumerate(matching_files):
            if task and task.isCanceled():
                self.log("Migrazione annullata dall'utente.")
                return False, "Operazione annullata dall'utente"

            file_path = os.path.join(root, filename)
            ext = os.path.splitext(filename)[1].lower()
            
            try:
                self.log(f"Migrazione: {filename}...")
                
                source_crs = None
                if ext in ['.tif', '.tiff']:
                    l = QgsRasterLayer(file_path, "tmp")
                    source_crs = l.crs()
                else:
                    l = QgsVectorLayer(file_path, "tmp", "ogr")
                    source_crs = l.crs()
                
                if source_crs and source_crs.authid() == target_crs.authid():
                    self.log(f"Salto {filename}: già nel CRS corretto.")
                    if task:
                        task.setProgress(int((i + 1) / total_files * 100))
                    continue

                from qgis.core import QgsProcessingFeedback
                feedback = QgsProcessingFeedback()
                if task and task.isCanceled():
                    feedback.cancel()
                    return False, "Operazione annullata"

                if ext in ['.tif', '.tiff']:
                    # Raster re-projection
                    temp_out = file_path.replace(ext, f"_reproj{ext}")
                    params = {
                        'INPUT': file_path,
                        'TARGET_CRS': target_crs_auth,
                        'RESAMPLING': 0, # Nearest Neighbour
                        'NODATA': -9999,
                        'DATA_TYPE': 0, # Use source data type
                        'OUTPUT': temp_out
                    }
                    processing.run("gdal:warpreproject", params, feedback=feedback)
                    
                    if os.path.exists(temp_out):
                        # Replace original
                        if os.path.exists(file_path): os.remove(file_path)
                        os.rename(temp_out, file_path)
                        count += 1
                else:
                    # Vector re-projection
                    temp_out = file_path.replace(ext, f"_reproj{ext}")
                    params = {
                        'INPUT': file_path,
                        'TARGET_CRS': target_crs,
                        'OUTPUT': temp_out
                    }
                    processing.run("native:reprojectlayer", params, feedback=feedback)
                    
                    if os.path.exists(temp_out):
                        # Replace original
                        if os.path.exists(file_path): os.remove(file_path)
                        os.rename(temp_out, file_path)
                        count += 1
                        
                # Trigger refresh if layer is in project
                layers = project.mapLayers().values()
                for layer in layers:
                    if layer.source() == file_path:
                        layer.triggerRepaint()
                        if hasattr(layer, 'dataProvider'):
                            if hasattr(layer.dataProvider(), 'reloadData'):
                                layer.dataProvider().reloadData()
                            
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")
                self.log(f"Errore migrazione {filename}: {str(e)}", Qgis.Warning)

            if task:
                task.setProgress(int((i + 1) / total_files * 100))

        # Force Project CRS to match
        project.setCrs(target_crs)
        
        msg = f"Migrazione completata: {count} file aggiornati."
        if errors:
            msg += f" ({len(errors)} errori)."
        
        self.log(msg)
        return True, msg

    def calculate_davenport_roughness(self, project_dir, center_x, center_y, width, height, rotation_deg):
        """
        Calculates the Davenport roughness length (z0) for a 3x3 grid around the active sub-area.
        Returns a dict mapping sector names (NW, N, NE, W, Center, E, SW, S, SE) to their parameters.
        """
        import math
        import os
        from qgis.core import (
            QgsPointXY, QgsGeometry, QgsVectorLayer, QgsRasterLayer, QgsFeatureRequest,
            QgsProject, QgsCoordinateTransform
        )
        from qgis.PyQt.QtCore import QVariant
        from .constants import FolderNames, LayerNames

        self.log("[Davenport] --- Inizio Calcolo Davenport Roughness ---")

        # Resolve the actual data directory where layers are stored
        project_path = QgsProject.instance().fileName()
        if project_path:
            project_name = os.path.splitext(os.path.basename(project_path))[0]
            data_dir = os.path.join(project_dir, f"EnviProtocol+{project_name}")
        else:
            data_dir = os.path.join(project_dir, "enviprotocol_data")

        self.log(f"[Davenport] Project Path: {project_path}")
        self.log(f"[Davenport] Resolved data_dir: {data_dir}")

        # Davenport nominal values mapping for ESA WorldCover classes
        ESA_DAVENPORT_MAP = {
            10: 0.50,   # Trees -> Very rough (0.5 m)
            20: 0.10,   # Shrubland -> Roughly open (0.1 m)
            30: 0.03,   # Grassland -> Open (0.03 m)
            40: 0.10,   # Cropland -> Roughly open (0.1 m)
            50: 0.50,   # Built-up -> Very rough (0.5 m)
            60: 0.01,   # Bare / sparse vegetation -> Smooth (0.01 m)
            70: 0.005,  # Snow and Ice -> Smooth (0.005 m)
            80: 0.0002, # Permanent water bodies -> Sea (0.0002 m)
            90: 0.03,   # Herbaceous wetland -> Open (0.03 m)
            95: 0.50,   # Mangroves -> Very rough (0.5 m)
            100: 0.005  # Moss and lichen -> Smooth (0.005 m)
        }

        # Define nominal Davenport classes for classification lookup
        davenport_classes = [
            (0.0002, "1. Sea"),
            (0.005,  "2. Smooth"),
            (0.03,   "3. Open"),
            (0.1,    "4. Roughly open"),
            (0.25,   "5. Rough"),
            (0.5,    "6. Very rough")
        ]

        # Locate the layers on disk dynamically
        def find_file(folder, extension, keyword=None):
            # First try the default location
            folder_path = os.path.join(data_dir, folder)
            paths_to_search = [folder_path]
            
            # Add project_dir as a fallback, just in case data_dir logic misses it
            if project_dir and os.path.exists(project_dir):
                paths_to_search.append(project_dir)
                
            for p in paths_to_search:
                if not os.path.exists(p):
                    continue
                for r, d, files in os.walk(p):
                    # If fallback searching in project_dir, ensure we are in the correct subfolder
                    if p == project_dir and folder not in r:
                        continue
                    
                    for f in files:
                        if f.lower().endswith(extension) and not f.startswith("."):
                            if keyword and keyword.lower() not in f.lower():
                                continue
                            return os.path.join(r, f)
            return ""

        def get_or_load_layer(layer_name, folder, extension, is_raster=True):
            # 1. Try to find it in the QGIS project by exact name
            project_layers = QgsProject.instance().mapLayersByName(layer_name)
            if project_layers and project_layers[0].isValid():
                self.log(f"[Davenport] Layer trovato nel progetto: {layer_name}")
                return project_layers[0]
                
            # 2. Not in project, try to load from disk
            file_path = find_file(folder, extension)
            if file_path and os.path.exists(file_path):
                self.log(f"[Davenport] Layer '{layer_name}' non nel progetto, caricamento da disco: {file_path}")
                if is_raster:
                    layer = QgsRasterLayer(file_path, layer_name, "gdal")
                else:
                    layer = QgsVectorLayer(file_path, layer_name, "ogr")
                
                if layer.isValid():
                    # Aggiunge al progetto senza metterlo in cima alla legenda
                    QgsProject.instance().addMapLayer(layer, False)
                    # Lo mettiamo in fondo all'albero e lo nascondiamo
                    root = QgsProject.instance().layerTreeRoot()
                    node = root.addLayer(layer)
                    if node:
                        node.setItemVisibilityChecked(False)
                        node.setExpanded(False)
                    return layer
                else:
                    self.log(f"[Davenport] ATTENZIONE: Il layer al percorso {file_path} è stato trovato ma risulta invalido per QGIS.")
            else:
                self.log(f"[Davenport] ATTENZIONE: File per '{layer_name}' non trovato nella cartella {folder}.")
            return None

        bld_layer = get_or_load_layer(LayerNames.BUILDINGS, FolderNames.TUM, ".gpkg", is_raster=False)
        canopy_layer = get_or_load_layer(LayerNames.CANOPY, FolderNames.ETH, ".tif", is_raster=True)
        landuse_layer = get_or_load_layer(LayerNames.LANDUSE, FolderNames.ESA, ".tif", is_raster=True)

        self.log(f"[Davenport] Validità Layer QGIS:")
        self.log(f"  - bld_layer: {bld_layer.isValid() if bld_layer else 'Non caricato o invalido'}")
        self.log(f"  - canopy_layer: {canopy_layer.isValid() if canopy_layer else 'Non caricato o invalido'}")
        self.log(f"  - landuse_layer: {landuse_layer.isValid() if landuse_layer else 'Non caricato o invalido'}")

        results = {}
        angle_rad = math.radians(rotation_deg)

        # Coordinate transform setup to handle any CRS mismatch dynamically
        project_crs = QgsProject.instance().crs()

        # Buildings Transforms
        bld_transform_fwd = None
        bld_transform_rev = None
        if bld_layer and bld_layer.isValid() and project_crs != bld_layer.crs():
            bld_transform_fwd = QgsCoordinateTransform(project_crs, bld_layer.crs(), QgsProject.instance())
            bld_transform_rev = QgsCoordinateTransform(bld_layer.crs(), project_crs, QgsProject.instance())

        # Canopy Transforms
        canopy_transform_fwd = None
        canopy_transform_rev = None
        if canopy_layer and canopy_layer.isValid() and project_crs != canopy_layer.crs():
            canopy_transform_fwd = QgsCoordinateTransform(project_crs, canopy_layer.crs(), QgsProject.instance())
            canopy_transform_rev = QgsCoordinateTransform(canopy_layer.crs(), project_crs, QgsProject.instance())

        # Landuse Transforms
        lu_transform_fwd = None
        lu_transform_rev = None
        if landuse_layer and landuse_layer.isValid() and project_crs != landuse_layer.crs():
            lu_transform_fwd = QgsCoordinateTransform(project_crs, landuse_layer.crs(), QgsProject.instance())
            lu_transform_rev = QgsCoordinateTransform(landuse_layer.crs(), project_crs, QgsProject.instance())

        # 3x3 Grid configurations: col, row offsets
        grid_sectors = [
            (-1, 1, "NW"),  (0, 1, "N"),  (1, 1, "NE"),
            (-1, 0, "W"),   (0, 0, "Center"), (1, 0, "E"),
            (-1, -1, "SW"), (0, -1, "S"), (1, -1, "SE")
        ]

        half_w = width / 2.0
        half_h = height / 2.0

        for col, row, label in grid_sectors:
            # 1. Compute rotated center of cell
            local_dx = col * width
            local_dy = row * height
            global_dx = local_dx * math.cos(angle_rad) - local_dy * math.sin(angle_rad)
            global_dy = local_dx * math.sin(angle_rad) + local_dy * math.cos(angle_rad)
            cell_cx = center_x + global_dx
            cell_cy = center_y + global_dy

            # 2. Compute corners of cell
            corners = [
                (-half_w, -half_h),
                (half_w, -half_h),
                (half_w, half_h),
                (-half_w, half_h)
            ]
            pts = []
            for cx, cy in corners:
                nx = cx * math.cos(angle_rad) - cy * math.sin(angle_rad)
                ny = cx * math.sin(angle_rad) + cy * math.cos(angle_rad)
                pts.append(QgsPointXY(cell_cx + nx, cell_cy + ny))
            
            cell_geom = QgsGeometry.fromPolygonXY([pts])
            cell_area = cell_geom.area()

            # 3. Analyze buildings
            sum_bld_area = 0.0
            sum_bld_height_area = 0.0
            if bld_layer and bld_layer.isValid():
                bbox = cell_geom.boundingBox()
                request_bbox = bld_transform_fwd.transformBoundingBox(bbox) if bld_transform_fwd else bbox
                request = QgsFeatureRequest().setFilterRect(request_bbox)
                for feat in bld_layer.getFeatures(request):
                    feat_geom = feat.geometry()
                    if bld_transform_rev:
                        feat_geom.transform(bld_transform_rev)
                    if feat_geom.intersects(cell_geom):
                        intersect_geom = feat_geom.intersection(cell_geom)
                        area = intersect_geom.area()
                        h = 0.0
                        idx = feat.fields().indexFromName("height")
                        if idx != -1:
                            val = feat.attribute("height")
                            try:
                                if val is not None and not isinstance(val, QVariant):
                                    h = float(val)
                            except:
                                pass
                        sum_bld_area += area
                        sum_bld_height_area += area * h

            f_bld = max(0.0, min(1.0, sum_bld_area / cell_area)) if cell_area > 0 else 0.0
            avg_bld_h = (sum_bld_height_area / sum_bld_area) if sum_bld_area > 0 else 0.0
            z0_bld = 0.1 * avg_bld_h if avg_bld_h > 0 else 0.1

            # 4. Analyze canopy
            sum_tree_height = 0.0
            num_tree_pixels = 0
            total_raster_pixels = 0
            if canopy_layer and canopy_layer.isValid():
                bbox = cell_geom.boundingBox()
                request_bbox = canopy_transform_fwd.transformBoundingBox(bbox) if canopy_transform_fwd else bbox
                provider = canopy_layer.dataProvider()
                x_res = canopy_layer.rasterUnitsPerPixelX()
                y_res = canopy_layer.rasterUnitsPerPixelY()
                width_px = max(1, int(request_bbox.width() / x_res))
                height_px = max(1, int(request_bbox.height() / y_res))
                
                block = provider.block(1, request_bbox, width_px, height_px)
                if block and block.isValid():
                    for r in range(height_px):
                        for c_idx in range(width_px):
                            px_x = request_bbox.xMinimum() + (c_idx + 0.5) * x_res
                            px_y = request_bbox.yMaximum() - (r + 0.5) * y_res
                            
                            pt = QgsPointXY(px_x, px_y)
                            if canopy_transform_rev:
                                pt = canopy_transform_rev.transform(pt)
                            pt_geom = QgsGeometry.fromPointXY(pt)
                            
                            if cell_geom.contains(pt_geom):
                                total_raster_pixels += 1
                                val = block.value(r, c_idx)
                                if not block.isNoData(r, c_idx) and val > 2.0:
                                    num_tree_pixels += 1
                                    sum_tree_height += val

            f_tree = (num_tree_pixels / total_raster_pixels) if total_raster_pixels > 0 else 0.0
            f_tree = max(0.0, min(f_tree, 1.0 - f_bld))
            avg_tree_h = (sum_tree_height / num_tree_pixels) if num_tree_pixels > 0 else 0.0
            z0_tree = 0.1 * avg_tree_h if avg_tree_h > 0 else 0.1

            # 5. Analyze ground / landuse (ESA)
            sum_lu_log_z0 = 0.0
            num_lu_pixels = 0
            if landuse_layer and landuse_layer.isValid():
                bbox = cell_geom.boundingBox()
                request_bbox = lu_transform_fwd.transformBoundingBox(bbox) if lu_transform_fwd else bbox
                provider = landuse_layer.dataProvider()
                x_res = landuse_layer.rasterUnitsPerPixelX()
                y_res = landuse_layer.rasterUnitsPerPixelY()
                width_px = max(1, int(request_bbox.width() / x_res))
                height_px = max(1, int(request_bbox.height() / y_res))
                
                block = provider.block(1, request_bbox, width_px, height_px)
                if block and block.isValid():
                    for r in range(height_px):
                        for c_idx in range(width_px):
                            px_x = request_bbox.xMinimum() + (c_idx + 0.5) * x_res
                            px_y = request_bbox.yMaximum() - (r + 0.5) * y_res
                            
                            pt = QgsPointXY(px_x, px_y)
                            if lu_transform_rev:
                                pt = lu_transform_rev.transform(pt)
                            pt_geom = QgsGeometry.fromPointXY(pt)
                            
                            if cell_geom.contains(pt_geom):
                                val = block.value(r, c_idx)
                                if not block.isNoData(r, c_idx):
                                    class_id = int(val)
                                    if class_id in ESA_DAVENPORT_MAP:
                                        z0_val = ESA_DAVENPORT_MAP[class_id]
                                        sum_lu_log_z0 += math.log(z0_val)
                                        num_lu_pixels += 1

            f_ground = max(0.0, 1.0 - f_bld - f_tree)
            z0_ground = math.exp(sum_lu_log_z0 / num_lu_pixels) if num_lu_pixels > 0 else 0.1

            # 6. Area-weighted logarithmic average for z0_eff
            log_z0_eff = 0.0
            if f_bld > 0:
                log_z0_eff += f_bld * math.log(z0_bld)
            if f_tree > 0:
                log_z0_eff += f_tree * math.log(z0_tree)
            if f_ground > 0:
                log_z0_eff += f_ground * math.log(z0_ground)

            total_f = f_bld + f_tree + f_ground
            z0_eff = math.exp(log_z0_eff / total_f) if total_f > 0 else 0.1

            # 7. Classify into closest Davenport class
            best_class = "4. Roughly open"
            min_dist = float('inf')
            log_z0_eff_val = math.log(z0_eff)
            for nominal_z0, class_name in davenport_classes:
                dist = abs(log_z0_eff_val - math.log(nominal_z0))
                if dist < min_dist:
                    min_dist = dist
                    best_class = class_name

            self.log(f"[Davenport] Cell {label}: "
                     f"f_bld={f_bld:.3f} (h={avg_bld_h:.1f}), "
                     f"f_tree={f_tree:.3f} (h={avg_tree_h:.1f}), "
                     f"f_ground={f_ground:.3f} (z0_ground={z0_ground:.4f}) "
                     f"-> z0_eff={z0_eff:.4f} ({best_class})")

            results[label] = {
                'z0': z0_eff,
                'davenport_class': best_class,
                'f_bld': f_bld,
                'h_bld': avg_bld_h,
                'f_tree': f_tree,
                'h_tree': avg_tree_h,
                'f_ground': f_ground,
                'geometry': cell_geom
            }

        return results

    def fix_envymap_raster_alignment(self, src_path, dest_path, center_x, center_y, width, height, rotation_deg, target_crs_auth, resampling_method="nearest"):
        """
        Georeferences and warps a misaligned EnvyMap raster to match a rotated sub-area's bounding box.
        """
        import os
        import math
        from osgeo import gdal, osr
        from qgis.core import Qgis

        self.log(f"Avvio correzione allineamento raster per {src_path}...")
        
        # 1. Open source dataset
        src_ds = gdal.Open(src_path)
        if not src_ds:
            return False, f"Impossibile aprire il raster sorgente: {src_path}"
            
        cols = src_ds.RasterXSize
        rows = src_ds.RasterYSize
        self.log(f"Dimensioni raster sorgente: {cols}x{rows} pixel")
        
        # 2. Determine target CRS WKT
        srs = osr.SpatialReference()
        if srs.SetFromUserInput(target_crs_auth) != 0:
            return False, f"CRS di destinazione non valido: {target_crs_auth}"
        target_wkt = srs.ExportToWkt()
        
        # 3. Calculate 4 corners of the subarea in target CRS
        angle_rad = math.radians(rotation_deg)
        dx = width / 2.0
        dy = height / 2.0
        
        # Coordinate calculation with rotation
        p0_x = center_x + (-dx * math.cos(angle_rad) - (-dy) * math.sin(angle_rad))
        p0_y = center_y + (-dx * math.sin(angle_rad) + (-dy) * math.cos(angle_rad))
        
        p1_x = center_x + (dx * math.cos(angle_rad) - (-dy) * math.sin(angle_rad))
        p1_y = center_y + (dx * math.sin(angle_rad) + (-dy) * math.cos(angle_rad))
        
        p2_x = center_x + (dx * math.cos(angle_rad) - dy * math.sin(angle_rad))
        p2_y = center_y + (dx * math.sin(angle_rad) + dy * math.cos(angle_rad))
        
        p3_x = center_x + (-dx * math.cos(angle_rad) - dy * math.sin(angle_rad))
        p3_y = center_y + (-dx * math.sin(angle_rad) + dy * math.cos(angle_rad))
        
        self.log(f"Angoli calcolati in metri (target CRS):"
                 f"\n- BL (P0): ({p0_x:.3f}, {p0_y:.3f})"
                 f"\n- BR (P1): ({p1_x:.3f}, {p1_y:.3f})"
                 f"\n- TR (P2): ({p2_x:.3f}, {p2_y:.3f})"
                 f"\n- TL (P3): ({p3_x:.3f}, {p3_y:.3f})")

        # 4. Find active mask corners in pixel space using self-calibrating bounding box
        first_band = src_ds.GetRasterBand(1)
        data = first_band.ReadAsArray()
        nodata = first_band.GetNoDataValue()
        
        import numpy as np
        if nodata is not None:
            active = (data != nodata)
        else:
            # Fallback when nodata is not explicitly defined in raster metadata
            active = (data > 0)
            
        y_indices, x_indices = np.where(active)
        if len(y_indices) == 0:
            return False, "Nessun dato attivo trovato nel raster sorgente."
            
        # Fast two-pass search for the optimal pixel-space rotation angle (minimizing bounding box area)
        best_angle = rotation_deg
        min_area = float('inf')
        start_a = max(0.0, rotation_deg - 15.0)
        end_a = min(90.0, rotation_deg + 15.0)
        
        for angle in np.arange(start_a, end_a, 1.0):
            rad = np.radians(angle)
            proj_u = x_indices * np.cos(rad) - y_indices * np.sin(rad)
            proj_v = x_indices * np.sin(rad) + y_indices * np.cos(rad)
            area = (proj_u.max() - proj_u.min()) * (proj_v.max() - proj_v.min())
            if area < min_area:
                min_area = area
                best_angle = angle
                
        start_a2 = max(0.0, best_angle - 1.0)
        end_a2 = min(90.0, best_angle + 1.0)
        for angle in np.arange(start_a2, end_a2, 0.05):
            rad = np.radians(angle)
            proj_u = x_indices * np.cos(rad) - y_indices * np.sin(rad)
            proj_v = x_indices * np.sin(rad) + y_indices * np.cos(rad)
            area = (proj_u.max() - proj_u.min()) * (proj_v.max() - proj_v.min())
            if area < min_area:
                min_area = area
                best_angle = angle
                
        self.log(f"Angolo di rotazione ottimale rilevato nei pixel: {best_angle:.2f}° (atteso: {rotation_deg:.2f}°)")
        
        # Project active pixels along the optimal angle
        rad = np.radians(best_angle)
        proj_u = x_indices * np.cos(rad) - y_indices * np.sin(rad)
        proj_v = x_indices * np.sin(rad) + y_indices * np.cos(rad)
        
        min_u, max_u = proj_u.min(), proj_u.max()
        min_v, max_v = proj_v.min(), proj_v.max()
        
        # Reconstruct the 4 corner points of the active diamond in pixel space
        cos_a, sin_a = np.cos(rad), np.sin(rad)
        
        tl_x = min_u * cos_a + min_v * sin_a
        tl_y = -min_u * sin_a + min_v * cos_a
        
        tr_x = max_u * cos_a + min_v * sin_a
        tr_y = -max_u * sin_a + min_v * cos_a
        
        br_x = max_u * cos_a + max_v * sin_a
        br_y = -max_u * sin_a + max_v * cos_a
        
        bl_x = min_u * cos_a + max_v * sin_a
        bl_y = -min_u * sin_a + max_v * cos_a
        
        self.log(f"Angoli matematici del diamante attivo ricostruiti (pixel):"
                 f"\n- Top-Left (TL): ({tl_x:.2f}, {tl_y:.2f})"
                 f"\n- Top-Right (TR): ({tr_x:.2f}, {tr_y:.2f})"
                 f"\n- Bottom-Right (BR): ({br_x:.2f}, {br_y:.2f})"
                 f"\n- Bottom-Left (BL): ({bl_x:.2f}, {bl_y:.2f})")
                 
        # Map pixel corners of the active diamond to subarea corners in target CRS:
        #   Top-Left in pixels -> P3 (Top-Left of subarea on map)
        #   Top-Right in pixels -> P2 (Top-Right of subarea on map)
        #   Bottom-Right in pixels -> P1 (Bottom-Right of subarea on map)
        #   Bottom-Left in pixels -> P0 (Bottom-Left of subarea on map)
        gcp_list = [
            gdal.GCP(p3_x, p3_y, 0, tl_x, tl_y),
            gdal.GCP(p2_x, p2_y, 0, tr_x, tr_y),
            gdal.GCP(p1_x, p1_y, 0, br_x, br_y),
            gdal.GCP(p0_x, p0_y, 0, bl_x, bl_y)
        ]

        
        # 5. Create a new temporary GeoTIFF from scratch (without any initial geotransform)
        temp_src = dest_path + ".tmp.tif"
        try:
            self.log(f"Creazione del file temporaneo da scratch in {temp_src}...")
            driver = gdal.GetDriverByName('GTiff')
            tmp_ds = driver.Create(temp_src, cols, rows, src_ds.RasterCount, src_ds.GetRasterBand(1).DataType)
            if not tmp_ds:
                return False, "Impossibile creare il file raster temporaneo per l'allineamento."
                
            # Copy band data, nodata, and color table
            for i in range(1, src_ds.RasterCount + 1):
                src_band = src_ds.GetRasterBand(i)
                tmp_band = tmp_ds.GetRasterBand(i)
                tmp_band.WriteArray(src_band.ReadAsArray())
                
                nodata = src_band.GetNoDataValue()
                if nodata is not None:
                    tmp_band.SetNoDataValue(nodata)
                    
                ct = src_band.GetColorTable()
                if ct:
                    tmp_band.SetColorTable(ct)
            
            # Reset geotransform to 0 and set GCPs
            tmp_ds.SetGeoTransform([0, 0, 0, 0, 0, 0])
            tmp_ds.SetGCPs(gcp_list, target_wkt)
            tmp_ds = None  # close and write to disk
        except Exception as e:
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except:
                    pass
            return False, f"Errore durante la creazione del raster temporaneo: {str(e)}"
            
        # Map resampling string to GDAL constant
        resamp_map = {
            "nearest": gdal.GRA_NearestNeighbour,
            "bilinear": gdal.GRA_Bilinear,
            "cubic": gdal.GRA_Cubic
        }
        gdal_resamp = resamp_map.get(resampling_method.lower(), gdal.GRA_NearestNeighbour)
        
        # Determine appropriate nodata value
        in_nodata = src_ds.GetRasterBand(1).GetNoDataValue()
        if in_nodata is not None:
            dst_nodata = in_nodata
        else:
            dtype = src_ds.GetRasterBand(1).DataType
            if dtype == gdal.GDT_Byte:
                dst_nodata = 0
            else:
                dst_nodata = -9999
        
        # Close source dataset to free file handles
        src_ds = None
                
        # 6. Execute GDAL Warp
        try:
            warp_options = gdal.WarpOptions(
                dstSRS=target_wkt,
                srcSRS=target_wkt,
                resampleAlg=gdal_resamp,
                dstNodata=dst_nodata,
                tps=True, # Force using GCPs via Thin Plate Splines
                format='GTiff'
            )
            
            self.log(f"Esecuzione di gdal.Warp (resampling={resampling_method}, nodata={dst_nodata})...")
            out_ds = gdal.Warp(dest_path, temp_src, options=warp_options)
            if out_ds is None:
                if os.path.exists(temp_src):
                    try:
                        os.remove(temp_src)
                    except:
                        pass
                return False, "GDAL Warp non ha prodotto alcun file di output."
                
            out_ds = None # close and flush
            
            # Clean up temp file
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except:
                    pass
                    
            self.log("Allineamento raster completato con successo!")
            return True, dest_path
        except Exception as warp_err:
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except:
                    pass
            return False, f"Errore durante l'esecuzione di GDAL Warp: {str(warp_err)}"

