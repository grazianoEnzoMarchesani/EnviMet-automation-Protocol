import os
import json
import random
from qgis.PyQt.QtCore import QVariant, QMetaType
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, 
    QgsFields, QgsField, QgsRectangle, QgsCoordinateReferenceSystem,
    Qgis, QgsMessageLog, QgsVectorFileWriter, QgsWkbTypes,
    QgsRasterLayer, QgsCoordinateTransform, QgsApplication
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
        QgsMessageLog.logMessage(message, "EnviProtocol-EM", level)

    def get_model_constraints(self, project_dir):
        """
        Analyzes Buildings and DTM to determine optimal ENVI-met constraints.
        Returns (lateral_margin, suggested_vertical_height, max_bld_h, max_dtm_z)
        """
        from .constants import FolderNames, FileNames
        max_bld_h = 20.0  # Default if layer missing
        max_dtm_z = 0.0

        # 1. Scan Buildings for Max Height
        bld_path = os.path.join(project_dir, FolderNames.TUM, FileNames.BUILDINGS)
        if os.path.exists(bld_path):
            try:
                res = processing.run("qgis:basicstatisticsforfields", {
                    'INPUT': bld_path, 'FIELD': 'height', 'OUTPUT': 'TEMPORARY_OUTPUT'
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
                'INPUT': vec_res['OUTPUT'], 'FIELD': ['DN'], 'OUTPUT': 'TEMPORARY_OUTPUT'
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

    def prepare_sub_area(self, extent, crs_auth_id, output_path, margin=0.0, geometry=None):
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
            
            # Set up fields and options
            fields = QgsFields()
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            
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
            
            feat = QgsFeature()
            feat.setGeometry(polygon)
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

    def process_dtm(self, project_dir, output_path, extent, crs_auth_id):
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
            clip_rlayer = QgsRasterLayer(temp_clip, "clipped")
            if clip_rlayer.crs().authid() != target_crs.authid():
                self.log(f"Reprojecting DTM from {clip_rlayer.crs().authid()} to {crs_auth_id}...")
                warp_params = {
                    'INPUT': temp_clip,
                    'TARGET_CRS': crs_auth_id,
                    'RESAMPLING': 0, # Nearest Neighbour
                    'NODATA': -9999,
                    'DATA_TYPE': 5,
                    'OUTPUT': output_path
                }
                processing.run("gdal:warpreproject", warp_params)
                if os.path.exists(temp_clip): os.remove(temp_clip)
            else:
                if os.path.exists(output_path): os.remove(output_path)
                os.rename(temp_clip, output_path)

            return True, output_path
        except Exception as e:
            return False, str(e)

    def process_vegetation_advanced(self, tcd_raster, eth_raster, output_path, aoi_geometry, extent, crs_auth_id, 
                                   tree_settings=None, buildings_layer=None, roads_layer=None):
        """Generates random tree points based on Tree Cover Density (TCD) and ETH height, with spatial cleaning."""
        if not os.path.exists(tcd_raster) or not os.path.exists(eth_raster):
            return False, "Dati TCD o ETH mancanti."

        # Tree settings defaults
        if not tree_settings:
            tree_settings = {
                "type": "Deciduous Trees",
                "density_mode": "auto", # auto, dense, sparse
                "tcd_threshold": 70
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
            clip_res = processing.run("gdal:cliprasterbyextent", {
                'INPUT': tcd_raster,
                'PROJWIN': x_extent,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_clipped = clip_res['OUTPUT']

            # 3. Vectorize TCD
            vec_res = processing.run("gdal:polygonize", {
                'INPUT': tcd_clipped, 'BAND': 1, 'FIELD': 'TCD', 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            
            # 4. Dissolve and Filter TCD (10% to 100%) to exclude NoData (255)
            dissolve_res = processing.run("native:dissolve", {
                'INPUT': vec_res['OUTPUT'], 'FIELD': ['TCD'], 'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            
            # Filter valid density range [10, 100] using expression to exclude NoData (255)
            filter_res = processing.run("native:extractbyexpression", {
                'INPUT': dissolve_res['OUTPUT'],
                'EXPRESSION': '"TCD" >= 10 AND "TCD" <= 100',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_filtered = filter_res['OUTPUT']
            
            # Reproject to metric (project CRS) to ensure "points per area" uses square meters
            repro_res = processing.run("native:reprojectlayer", {
                'INPUT': tcd_filtered,
                'TARGET_CRS': target_crs_obj.authid(),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            tcd_metric = repro_res['OUTPUT']
            
            # (Removed redundant block)
            
            # --- START ETH FALLBACK LOGIC ---
            # Extract ETH where TCD is missing to avoid underestimation
            self.log("Processing ETH raster for fallback tree generation...")
            
            # Correctly handle ETH CRS which might differ from TCD
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
            eth_only_metric = None

            if isinstance(eth_clipped_path, str) and os.path.exists(eth_clipped_path):
                vec_eth_res = processing.run("gdal:polygonize", {
                    'INPUT': eth_clipped_path, 'BAND': 1, 'FIELD': 'ETH', 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                
                filter_eth_res = processing.run("native:extractbyexpression", {
                    'INPUT': vec_eth_res['OUTPUT'],
                    'EXPRESSION': '"ETH" >= 2',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                
                dissolve_eth_res = processing.run("native:dissolve", {
                    'INPUT': filter_eth_res['OUTPUT'], 'OUTPUT': 'TEMPORARY_OUTPUT'
                })

                repro_eth_res = processing.run("native:reprojectlayer", {
                    'INPUT': dissolve_eth_res['OUTPUT'],
                    'TARGET_CRS': crs_auth_id,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                
                # Find ETH areas isolated from TCD
                diff_res = processing.run("native:difference", {
                    'INPUT': repro_eth_res['OUTPUT'],
                    'OVERLAY': tcd_metric,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                eth_only_metric = diff_res['OUTPUT']
            else:
                self.log("Avviso: Ritaglio raster ETH fallito o vuoto. Procedo solo con TCD.")
            # --- END ETH FALLBACK LOGIC ---
            
            # 5. Generate Random Points proportional to TCD
            algo_id = "native:randompointsinsidepolygons"
            if not QgsApplication.processingRegistry().algorithmById(algo_id):
                algo_id = "qgis:randompointsinsidepolygons"

            d_mult = tree_settings.get("density_multiplier", 1.0)
            density_expr = f'("TCD" / 100.0) * 0.01 * {d_mult}'
            
            pts_res = processing.run(algo_id, {
                'INPUT': tcd_metric,
                'STRATEGY': 1, # Points per area (density)
                'VALUE': 0.01,
                'EXPRESSION': density_expr,
                'MIN_DISTANCE': 2.0, # Minimum distance between trees (meters)
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            
            # Generate Points for ETH-only areas, if available
            if eth_only_metric:
                eth_only_density_expr = f'0.50 * 0.01 * {d_mult}' 
                pts_eth_res = processing.run(algo_id, {
                    'INPUT': eth_only_metric,
                    'STRATEGY': 1,
                    'VALUE': 0.01,
                    'EXPRESSION': eth_only_density_expr,
                    'MIN_DISTANCE': 2.0,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                
                # Merge the two point sets
                merge_res = processing.run("native:mergevectorlayers", {
                    'LAYERS': [pts_res['OUTPUT'], pts_eth_res['OUTPUT']],
                    'CRS': crs_auth_id,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                pts_out = merge_res['OUTPUT']
            else:
                pts_out = pts_res['OUTPUT']
            
            # --- START SPATIAL CLEANING ---
            # Remove points that fall on buildings or roads
            if buildings_layer:
                self.log("Cleaning vegetation: Removing points from buildings...")
                pts_clean_bld = processing.run("native:difference", {
                    'INPUT': pts_out,
                    'OVERLAY': buildings_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                pts_out = pts_clean_bld['OUTPUT']
                
            if roads_layer:
                self.log("Cleaning vegetation: Removing points from roads...")
                pts_clean_roads = processing.run("native:difference", {
                    'INPUT': pts_out,
                    'OVERLAY': roads_layer,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                pts_out = pts_clean_roads['OUTPUT']
            
            # --- MANDATORY GEOMETRY CLEANING ---
            # Some operations (like difference) might leave features with null geometry
            # if points were covered. native:rastersampling might complain if they are not removed.
            clean_res = processing.run("native:removenullgeometries", {
                'INPUT': pts_out,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            pts_out = clean_res['OUTPUT']
            # --- END SPATIAL CLEANING ---
            
            pts_layer = pts_out if not isinstance(pts_out, str) else QgsVectorLayer(pts_out, "temp_pts", "ogr")

            if not pts_layer or not pts_layer.isValid() or pts_layer.featureCount() == 0:
                return False, "Nessun albero generato dai layer TCD e ETH."

            # 6. Sample ETH Heights
            sample_res = processing.run("native:rastersampling", {
                'INPUT': pts_layer,
                'RASTERCOPY': eth_raster,
                'COLUMN_PREFIX': 'height_',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            sampled_layer = sample_res['OUTPUT']
            
            # 7. Sample TCD Values (for smart density)
            # We need to sample TCD too if density_mode is auto
            if tree_settings.get("density_mode") == "auto":
                sample_tcd_res = processing.run("native:rastersampling", {
                    'INPUT': sampled_layer,
                    'RASTERCOPY': tcd_clipped,
                    'COLUMN_PREFIX': 'tcd_',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                final_pts = sample_tcd_res['OUTPUT']
            else:
                final_pts = sampled_layer

            # 8. Clean up and Assign ENVI_IDs
            final_vec = final_pts if not isinstance(final_pts, str) else QgsVectorLayer(final_pts, "final", "ogr")
            final_vec.startEditing()
            final_vec.addAttribute(QgsField("ENVI_ID", QMetaType.QString, "string", 6))
            final_vec.addAttribute(QgsField("Name", QMetaType.QString, "string"))
            final_vec.updateFields()
            
            f_names = [f.name() for f in final_vec.fields()]
            idx_h = -1
            for target in ["height_1", "height", "height_1_1", "SAMPLE"]:
                if target in f_names:
                    idx_h = final_vec.fields().indexFromName(target)
                    break
            
            idx_tcd = -1
            for target in ["tcd_1", "tcd", "tcd_1_1", "SAMPLE_1"]:
                if target in f_names:
                    idx_tcd = final_vec.fields().indexFromName(target)
                    break

            idx_envi = final_vec.fields().indexFromName("ENVI_ID")
            idx_name = final_vec.fields().indexFromName("Name")
            
            # Load DB for lookup
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "envimet_db.json")
            db_plants = {}
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                    db_plants = db.get("3d_plants", {}).get("Abstract", {})
            except:
                pass

            tree_type = tree_settings.get("type", "Deciduous Trees")
            type_data = db_plants.get(tree_type, {})
            d_mode = tree_settings.get("density_mode", "auto")
            t_thresh = tree_settings.get("tcd_threshold", 70)
            pref_shape = tree_settings.get("shape", "Random")

            for feat in final_vec.getFeatures():
                h = feat.attributes()[idx_h]
                if h is None or (isinstance(h, QVariant) and h.isNull()) or h < 2:
                    h_cat = None # Skip very small "trees" or no data
                elif h < 10: h_cat = "Small"
                elif h < 20: h_cat = "Medium"
                else: h_cat = "Large"

                if not h_cat or not type_data:
                    final_vec.changeAttributeValue(feat.id(), idx_envi, "0000XX")
                    continue

                # Determine Canopy Density
                if d_mode == "auto":
                    tcd_val = feat.attributes()[idx_tcd] if idx_tcd != -1 else 0
                    c_density = "dense canopy" if (tcd_val and tcd_val >= t_thresh) else "sparse canopy"
                else:
                    c_density = f"{d_mode} canopy"

                # Get the list of plants for this Category/Density
                size_data = type_data.get(h_cat, {})
                # If palm trees, size_data IS the list
                if isinstance(size_data, list):
                    plants = size_data
                else:
                    plants = size_data.get(c_density, size_data.get("dense canopy", []))

                if plants:
                    # Filter by shape if requested
                    selected_plant = None
                    if pref_shape == "Random":
                        # Pick a random one from the list to vary the forest look
                        selected_plant = random.choice(plants)
                    elif pref_shape == "Palm":
                        selected_plant = plants[0]
                    else:
                        # Try to find a match for the specific shape
                        # (e.g. "Cylindric", "Heart-shaped", "Spherical", "Conic")
                        matches = [p for p in plants if pref_shape.lower() in p["name"].lower()]
                        if matches:
                            selected_plant = random.choice(matches) # Multiple trunk sizes might exist
                        else:
                            selected_plant = plants[0] # Fallback to first

                    final_vec.changeAttributeValue(feat.id(), idx_envi, selected_plant["envi_id"])
                    final_vec.changeAttributeValue(feat.id(), idx_name, selected_plant["name"])
                else:
                    final_vec.changeAttributeValue(feat.id(), idx_envi, "0010MO") # Generic fallback

            final_vec.commitChanges()
            
            # --- 8.5 Precise Clipping (Custom Sub Area) ---
            if aoi_geometry:
                self.log("Clipping vegetation to precise Sub Area geometry...")
                temp_mask = QgsVectorLayer(f"Polygon?crs={crs_auth_id}", "precise_mask", "memory")
                temp_mask.startEditing()
                f_mask = QgsFeature()
                f_mask.setGeometry(aoi_geometry)
                temp_mask.addFeature(f_mask)
                temp_mask.commitChanges()
                
                clip_res = processing.run("native:clip", {
                    'INPUT': final_vec,
                    'OVERLAY': temp_mask,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                final_vec = clip_res['OUTPUT']
            
            # --- 9. Save final Points ---
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            
            write_layer = final_vec if not isinstance(final_vec, str) else QgsVectorLayer(final_vec, "to_write", "ogr")
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                write_layer, 
                output_path, 
                QgsProject.instance().transformContext(), 
                options
            )
            
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
                'OUTPUT': 'TEMPORARY_OUTPUT'
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
                    'OUTPUT': 'TEMPORARY_OUTPUT'
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
                    'LAYERS': [esa_layer, tcd_layer], 'OUTPUT': 'TEMPORARY_OUTPUT'
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
                    'INPUT': final_layer, 'OVERLAY': road_layer, 'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                final_layer = diff_res['OUTPUT']
            
            # Remove null geometries that may result from difference operations
            if final_layer:
                clean_res = processing.run("native:removenullgeometries", {
                    'INPUT': final_layer, 'OUTPUT': 'TEMPORARY_OUTPUT'
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
                'OUTPUT': 'memory:temp_bld_lev'
            }
            reproj_res = processing.run("native:reprojectlayer", reproj_params)
            vlayer = reproj_res['OUTPUT']
            
            if isinstance(vlayer, str):
                vlayer = QgsVectorLayer(vlayer, "bld_lev", "memory")

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

    def migrate_project_to_target_crs(self, target_crs_auth):
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

        # Recursively find .gpkg and .tif files
        for root, dirs, files in os.walk(data_dir):
            for filename in files:
                file_path = os.path.join(root, filename)
                ext = os.path.splitext(filename)[1].lower()
                
                if ext not in ['.gpkg', '.tif', '.tiff', '.geojson', '.shp']:
                    continue
                
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
                        continue

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
                        processing.run("gdal:warpreproject", params)
                        
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
                        processing.run("native:reprojectlayer", params)
                        
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

        # Force Project CRS to match
        project.setCrs(target_crs)
        
        msg = f"Migrazione completata: {count} file aggiornati."
        if errors:
            msg += f" ({len(errors)} errori)."
        
        self.log(msg)
        return True, msg
