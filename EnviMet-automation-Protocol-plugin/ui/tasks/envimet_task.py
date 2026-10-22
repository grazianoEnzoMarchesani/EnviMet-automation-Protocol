# -*- coding: utf-8 -*-
"""
EnviProtocol Dashboard - ENVI-met Preparation Task
Background task for data clipping and vectorization.
"""

import os
from qgis.core import (
    QgsTask, QgsMessageLog, Qgis, QgsProject, QgsVectorLayer
)
from ...core.envimet_manager import ENVImetManager
from ...core.constants import FolderNames, FileNames

class ENVImetTask(QgsTask):
    """Background task to prepare GIS data for ENVI-met."""
    
    def __init__(self, data_manager, extent, crs, 
                 landuse_mapping=None, road_widths=None, 
                 road_materials=None, plant_mapping=None, 
                 tree_settings=None, building_settings=None, 
                 do_leveling=True, sub_area_geometry=None,
                 sub_area_name=None, sub_area_params=None):
        super().__init__("Preparazione Dati ENVI-met", QgsTask.CanCancel)
        self.data_manager = data_manager
        self.extent = extent
        self.crs = crs
        self.landuse_mapping = landuse_mapping
        self.road_widths = road_widths
        self.road_materials = road_materials
        self.plant_mapping = plant_mapping
        self.tree_settings = tree_settings
        self.building_settings = building_settings
        self.do_leveling = do_leveling
        self.sub_area_geometry = sub_area_geometry
        self.sub_area_name = sub_area_name
        self.sub_area_params = sub_area_params
        self.em_manager = ENVImetManager()
        self.success = False
        self.message = ""

    def log(self, message, level=Qgis.Info):
        """Helper to log messages to the QGIS Message Log."""
        QgsMessageLog.logMessage(message, "EnviProtocol", level)

    def run(self):
        """Execute the preparation logic."""
        try:
            if self.isCanceled(): return False
            project_path = QgsProject.instance().fileName()
            project_dir = os.path.dirname(project_path)
            data_dir_name = self.data_manager.get_data_dir_name()
            root_data_dir = os.path.join(project_dir, data_dir_name)
            
            export_dir = os.path.join(root_data_dir, FolderNames.ENVIMET)
            if not os.path.exists(export_dir):
                os.makedirs(export_dir)

            # 1. Analyze constraints using the correct data directory
            self.setProgress(10)
            if self.isCanceled(): return False
            margin, suggested_z, max_h, max_z = self.em_manager.get_model_constraints(root_data_dir)
            
            # 2. Prepare Sub Area
            self.setProgress(20)
            if self.isCanceled(): return False
            
            sub_name = self.sub_area_name or "default"
            if sub_name == "default":
                file_name = FileNames.EM_SUB_AREA
            else:
                file_name = f"sub_area_{sub_name}.gpkg"
                
            subarea_path = os.path.join(export_dir, file_name)
            crs_id = self.crs if isinstance(self.crs, str) else self.crs.authid()
            
            w = self.sub_area_params.get("width", 0.0) if self.sub_area_params else 0.0
            h = self.sub_area_params.get("height", 0.0) if self.sub_area_params else 0.0
            rot = self.sub_area_params.get("rotation", 0.0) if self.sub_area_params else 0.0
            gs = self.sub_area_params.get("grid_size", 0.0) if self.sub_area_params else 0.0
            
            ok, msg = self.em_manager.prepare_sub_area(
                self.extent, crs_id, subarea_path, margin=margin, geometry=self.sub_area_geometry,
                name=sub_name, width=w, height=h, rotation=rot, grid_size=gs
            )
            if not ok:
                self.message = f"Sub Area: {msg}"
                return False

            from qgis.core import QgsGeometry, Qgis
            # Se è presente una sub_area_geometry ruotata, usiamo quella (più un buffer di sicurezza) 
            # affinché i layer ritagliati seguano la rotazione dell'area anziché un bounding box non ruotato.
            # Questo evita "vuoti" (triangoli senza dati) agli angoli del dominio ruotato.
            if self.sub_area_geometry and not self.sub_area_geometry.isEmpty():
                aoi_poly = QgsGeometry(self.sub_area_geometry)
                # Aggiungiamo il margin + 50 metri come richiesto dall'utente per sicurezza
                buffer_dist = margin + 50.0
                # Utilizziamo JoinStyle.Miter per evitare angoli arrotondati (bevel) e mantenere spigoli vivi
                aoi_poly = aoi_poly.buffer(buffer_dist, 5, Qgis.EndCapStyle.Square, Qgis.JoinStyle.Miter, 2.0)
                clip_extent = aoi_poly.boundingBox()
            else:
                aoi_poly = QgsGeometry.fromRect(self.extent)
                if margin > 0:
                    aoi_poly = aoi_poly.buffer(margin, 5)
                clip_extent = aoi_poly.boundingBox()

            def find_file(folder, extension, keyword=None):
                folder_path = os.path.join(root_data_dir, folder)
                if not os.path.exists(folder_path): return None
                for root, dirs, files in os.walk(folder_path):
                    for f in files:
                        if f.lower().endswith(extension) and not f.startswith("."):
                            if keyword and keyword.lower() not in f.lower():
                                continue
                            return os.path.join(root, f)
                return None

            # 3. Vectorize Land Use (ESA)
            self.setProgress(40)
            if self.isCanceled(): return False
            road_layer = None
            esa_path = find_file(FolderNames.ESA, ".tif", "ESA")
            if esa_path:
                self.log(f"Processamento Land Use ESA: {esa_path}")
                surface_path = os.path.join(export_dir, FileNames.EM_SURFACES)
                
                # Pre-calculate road layer to share between surfaces and plants
                self.log("Preprocessing reti stradali...")
                road_layer = self.em_manager._process_osm_roads(clip_extent, crs_id, self.road_widths, self.road_materials)
                
                if self.isCanceled(): return False
                ok, msg = self.em_manager.vectorize_land_use(
                    esa_path, surface_path, clip_extent, 
                    custom_mapping=self.landuse_mapping,
                    road_widths=self.road_widths,
                    road_materials=self.road_materials,
                    road_layer=road_layer,
                    precise_geometry=aoi_poly,
                    crs_auth_id=crs_id
                )
                if not ok:
                    QgsMessageLog.logMessage(f"Avviso Land Use: {msg}", "EnviProtocol", Qgis.Warning)
                else:
                    self.log(f"Superfici salvate: {surface_path}")
            else:
                QgsMessageLog.logMessage(f"Dati Land Use (ESA) non trovati in {FolderNames.ESA}", "EnviProtocol", Qgis.Warning)

            # 4. Process Buildings (TUM)
            self.setProgress(60)
            if self.isCanceled(): return False
            out_bld = os.path.join(export_dir, FileNames.EM_BUILDINGS)
            bld_path = find_file(FolderNames.TUM, ".gpkg") # Any .gpkg in folder
            if bld_path:
                self.log(f"Processamento Edifici: {bld_path}")
                ok, msg = self.em_manager.process_buildings(bld_path, out_bld, aoi_poly, crs_id, 
                                                            building_settings=self.building_settings)
                if not ok:
                    QgsMessageLog.logMessage(f"Avviso Edifici: {msg}", "EnviProtocol", Qgis.Warning)
                else:
                    self.log(f"Edifici salvati: {out_bld}")
            else:
                QgsMessageLog.logMessage(f"Dati Edifici (TUM) non trovati in {FolderNames.TUM}", "EnviProtocol", Qgis.Warning)

            # 5. Process DTM (Tinitaly)
            self.setProgress(80)
            if self.isCanceled(): return False
            terrain_path = os.path.join(export_dir, FileNames.DTM)
            ok, msg = self.em_manager.process_dtm(root_data_dir, terrain_path, clip_extent, crs_id, precise_geometry=aoi_poly)
            if not ok:
                QgsMessageLog.logMessage(f"Avviso DTM: {msg}", "EnviProtocol", Qgis.Warning)
            else:
                self.log(f"DTM salvato: {terrain_path}")
                # Level terrain under buildings if explicitly requested and buildings exist
                if self.do_leveling:
                    if self.isCanceled(): return False
                    if os.path.exists(out_bld):
                        self.em_manager.level_terrain_under_buildings(terrain_path, out_bld)
                    else:
                        self.log("Livellamento saltato: file edifici non trovato.", Qgis.Info)
                else:
                    self.log("Livellamento terreno disattivato dall'utente.", Qgis.Info)

            # 6. Process Vegetation (Advanced TCD + ETH)
            self.setProgress(90)
            if self.isCanceled(): return False
            tcd_path = find_file(FolderNames.HRL, ".tif", "TCD")
            eth_path = find_file(FolderNames.ETH, ".tif")
            if tcd_path or eth_path:
                self.log(f"Processamento Vegetazione: TCD={tcd_path}, ETH={eth_path}")
                veg_path = os.path.join(export_dir, FileNames.EM_VEGETATION)
                
                # Retrieve layers for cleaning if available
                bld_layer = None
                if os.path.exists(out_bld):
                    bld_layer = QgsVectorLayer(out_bld, "bld_for_clean", "ogr")
                
                # road_layer was defined in step 3
                if self.isCanceled(): return False
                
                ok, msg = self.em_manager.process_vegetation_advanced(
                    tcd_path, eth_raster=eth_path, output_path=veg_path, 
                    aoi_geometry=aoi_poly, extent=clip_extent, crs_auth_id=crs_id,
                    tree_settings=self.tree_settings,
                    buildings_layer=bld_layer,
                    roads_layer=road_layer,
                    esa_raster=esa_path
                )
                del bld_layer
                if not ok:
                    QgsMessageLog.logMessage(f"Avviso Vegetazione: {msg}", "EnviProtocol", Qgis.Warning)
                else:
                    self.log(f"Vegetazione salvata: {veg_path}")
            else:
                QgsMessageLog.logMessage(f"Dati Vegetazione (TCD/ETH) non trovati.", "EnviProtocol", Qgis.Warning)
            
            # 7. Process Simple Plants (ESA + TCD Undergrowth)
            self.setProgress(95)
            if self.isCanceled(): return False
            if esa_path:
                self.log(f"Processamento Simple Plants (ESA + TCD): {esa_path}")
                simple_plants_path = os.path.join(export_dir, FileNames.EM_SIMPLE_PLANTS)
                ok, msg = self.em_manager.process_simple_plants(
                    esa_path, tcd_path, simple_plants_path, clip_extent, crs_id, 
                    road_layer=road_layer,
                    custom_mapping=self.plant_mapping,
                    precise_geometry=aoi_poly
                )
                if not ok:
                    # Not critical, some areas might not have simple plants
                    QgsMessageLog.logMessage(f"Avviso Simple Plants: {msg}", "EnviProtocol", Qgis.Info)
                else:
                    self.log(f"Simple Plants salvate: {simple_plants_path}")

            self.setProgress(100)
            if self.isCanceled(): return False
            self.success = True
            return True
        except Exception as e:
            self.message = str(e)
            return False

    def finished(self, result):
        """Called when the task is finished."""
        if result:
            QgsMessageLog.logMessage("Preparazione ENVI-met completata con successo.", "EnviProtocol", Qgis.Info)
        else:
            QgsMessageLog.logMessage(f"Errore preparazione ENVI-met: {self.message}", "EnviProtocol", Qgis.Warning)
