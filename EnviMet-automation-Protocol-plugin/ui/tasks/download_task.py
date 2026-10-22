# -*- coding: utf-8 -*-
"""
EnviProtocol Download Task
This module contains the task class for background data acquisition.
"""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import (
    QgsTask, QgsMessageLog, Qgis, QgsProject,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry
)
from ...core.exceptions import EnviError, EnviDataError, EnviCriticalError


class DownloadTask(QgsTask):
    """Task for running all data downloads in the background."""
    
    # Signal to update UI with detailed progress: (step_name, step_num, total_steps, percent)
    progressUpdated = pyqtSignal(str, int, int, int)
    
    # Mapping from checkbox names to human-readable step names
    STEP_NAMES = {
        "Tinitaly (DTM 10m)": "Download DTM Tinitaly",
        "TUM (Edifici H 10m)": "Download Edifici TUM",
        "ETH (Alberi H 10m)": "Download Altezze Alberi ETH",
        "ESA WorldCover (Land Use)": "Download Land Cover ESA",
        "OSM Roads (Vettoriale)": "Download Strade OSM",
        "Copernicus HRL (10m)": "Download Impermeabilità HRL",
        "Tree Cover Density (Copernicus)": "Download Tree Cover Density"
    }
    
    def __init__(self, data_manager, selected_checks, extent, crs, tiles):
        super().__init__("Download Dati EnviProtocol", QgsTask.CanCancel)
        self.data_manager = data_manager
        self.selected_checks = selected_checks
        self.extent = extent
        self.crs = crs
        self.tiles = tiles
        self.success = False
        self.message = ""
        self.error_count = 0
    
    def emit_progress(self, check_name, step_num, total_steps):
        """Emit progress signal with calculated percentage."""
        step_name = self.STEP_NAMES.get(check_name, check_name)
        percent = int((step_num / total_steps) * 100)
        self.progressUpdated.emit(step_name, step_num, total_steps, percent)

    def run(self):
        def task_log(msg, level=Qgis.Info):
            QgsMessageLog.logMessage(msg, "EnviProtocol", level)

        try:
            total_steps = sum(1 for val in self.selected_checks.values() if val)
            current_step = 0
            
            # 1. Tinitaly
            if self.selected_checks.get("Tinitaly (DTM 10m)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("Tinitaly (DTM 10m)", current_step, total_steps)
                
                for i, tile in enumerate(self.tiles):
                    if self.isCanceled(): return False
                    task_log(f"Download Tinitaly {i+1}/{len(self.tiles)}: {tile}")
                    
                    def make_tinitaly_progress_cb(tile_idx):
                        def cb(dl, total):
                            if total > 0:
                                tile_fraction = dl / total
                                overall_fraction = (tile_idx + tile_fraction) / len(self.tiles)
                                sub_percent = int(((current_step - 1) + overall_fraction) / total_steps * 100)
                                percent = int(tile_fraction * 100)
                                self.progressUpdated.emit(f"Download DTM Tinitaly ({percent}%, tile {tile_idx+1}/{len(self.tiles)})", current_step, total_steps, sub_percent)
                                self.setProgress(sub_percent)
                        return cb
                        
                    success, msg = self.data_manager.download_tinitaly_tile(
                        tile,
                        progress_callback=make_tinitaly_progress_cb(i),
                        cancel_check=self.isCanceled
                    )
                    if self.isCanceled(): return False
                    if not success:
                        task_log(f"⚠ Tinitaly {tile}: {msg}", Qgis.Warning)
                        self.error_count += 1
                    
                    sub_percent = int(((current_step - 1) + (i+1)/len(self.tiles)) / total_steps * 100)
                    self.setProgress(sub_percent)

            # 2. TUM Building Heights
            if self.selected_checks.get("TUM (Edifici H 10m)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("TUM (Edifici H 10m)", current_step, total_steps)
                
                source_crs = QgsCoordinateReferenceSystem(self.crs)
                wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
                
                # Use project context for transformation (required for background tasks in QGIS 3)
                transform = QgsCoordinateTransform(source_crs, wgs84_crs, QgsProject.instance().transformContext())
                
                aoi_geom = QgsGeometry.fromRect(self.extent)
                # transform() returns 0 on success, error code otherwise
                res = aoi_geom.transform(transform)
                if res != 0:
                    task_log(f"✗ Trasformazione AOI Geometria fallita (Codice: {res})", Qgis.Warning)
                    # We continue but TUM might fail later

                for category in self.data_manager.tum_categories:
                    if self.isCanceled(): return False
                    task_log(f"Acquisizione TUM {category}...")
                    
                    def tum_progress_cb(dl, total):
                        if total > 0:
                            percent = int((dl / total) * 100)
                            sub_percent = int(((current_step - 1) + (dl / total)) / total_steps * 100)
                            self.progressUpdated.emit(f"Download Edifici TUM ({percent}%)", current_step, total_steps, sub_percent)
                            self.setProgress(sub_percent)
                        else:
                            mb = dl // (1024 * 1024)
                            sub_percent = int(current_step / total_steps * 100)
                            self.progressUpdated.emit(f"Download Edifici TUM ({mb} MB)", current_step, total_steps, sub_percent)
                            self.setProgress(sub_percent)

                    # Use the QgsGeometry constructor to create a copy, as 'clone()' is not available on QgsGeometry in PyQGIS
                    res_list = self.data_manager.download_tum_data(
                        category=category, 
                        aoi_geometry=QgsGeometry(aoi_geom),
                        progress_callback=tum_progress_cb,
                        cancel_check=self.isCanceled
                    )
                    if self.isCanceled(): return False
                    for file_id, success, msg in res_list:
                        if not success:
                            task_log(f"⚠ TUM {file_id}: {msg}", Qgis.Warning)
                            self.error_count += 1
                self.setProgress(int(current_step / total_steps * 100))

            # 3. ETH Canopy Height
            if self.selected_checks.get("ETH (Alberi H 10m)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("ETH (Alberi H 10m)", current_step, total_steps)
                task_log("Acquisizione ETH Global Canopy Height...")
                
                def eth_progress_cb(dl, total):
                    if total > 0:
                        percent = int((dl / total) * 100)
                        sub_percent = int(((current_step - 1) + (dl / total)) / total_steps * 100)
                        self.progressUpdated.emit(f"Download Altezze Alberi ETH ({percent}%)", current_step, total_steps, sub_percent)
                        self.setProgress(sub_percent)
                    else:
                        mb = dl // (1024 * 1024)
                        sub_percent = int(current_step / total_steps * 100)
                        self.progressUpdated.emit(f"Download Altezze Alberi ETH ({mb} MB)", current_step, total_steps, sub_percent)
                        self.setProgress(sub_percent)

                self.data_manager.fetch_eth_canopy(
                    self.extent, 
                    self.crs,
                    progress_callback=eth_progress_cb,
                    cancel_check=self.isCanceled
                )
                if self.isCanceled(): return False
                self.setProgress(int(current_step / total_steps * 100))

            # 4. ESA WorldCover
            if self.selected_checks.get("ESA WorldCover (Land Use)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("ESA WorldCover (Land Use)", current_step, total_steps)
                task_log("Acquisizione ESA WorldCover...")
                
                def esa_progress_cb(dl, total):
                    if total > 0:
                        percent = int((dl / total) * 100)
                        sub_percent = int(((current_step - 1) + (dl / total)) / total_steps * 100)
                        self.progressUpdated.emit(f"Download Land Cover ESA ({percent}%)", current_step, total_steps, sub_percent)
                        self.setProgress(sub_percent)
                    else:
                        mb = dl // (1024 * 1024)
                        sub_percent = int(current_step / total_steps * 100)
                        self.progressUpdated.emit(f"Download Land Cover ESA ({mb} MB)", current_step, total_steps, sub_percent)
                        self.setProgress(sub_percent)

                self.data_manager.fetch_esa_worldcover(
                    self.extent, 
                    self.crs,
                    progress_callback=esa_progress_cb,
                    cancel_check=self.isCanceled
                )
                if self.isCanceled(): return False
                self.setProgress(int(current_step / total_steps * 100))

            # 5. OSM Roads
            if self.selected_checks.get("OSM Roads (Vettoriale)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("OSM Roads (Vettoriale)", current_step, total_steps)
                task_log("Acquisizione Strade da OpenStreetMap...")
                success, msg = self.data_manager.fetch_osm_roads(
                    self.extent, self.crs, log_callback=task_log, cancel_check=self.isCanceled
                )
                if self.isCanceled(): return False
                if not success:
                    task_log(f"⚠ OSM Roads: {msg}", Qgis.Warning)
                    self.error_count += 1
                self.setProgress(int(current_step / total_steps * 100))

            # 7. Copernicus HRL
            if self.selected_checks.get("Copernicus HRL (10m)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("Copernicus HRL (10m)", current_step, total_steps)
                task_log("Acquisizione Copernicus HRL Imperviousness...")
                self.data_manager.fetch_copernicus_hrl(self.extent, self.crs, log_callback=task_log)
                self.setProgress(int(current_step / total_steps * 100))

            # 8. Copernicus Tree Cover Density
            if self.selected_checks.get("Tree Cover Density (Copernicus)"):
                current_step += 1
                if self.isCanceled(): return False
                self.emit_progress("Tree Cover Density (Copernicus)", current_step, total_steps)
                task_log("Acquisizione Copernicus Tree Cover Density (TCD)...")
                self.data_manager.fetch_tree_cover_density(self.extent, self.crs, log_callback=task_log)
                self.setProgress(int(current_step / total_steps * 100))

            self.success = True
            return True
        except EnviCriticalError as e:
            self.message = e.user_message
            task_log(f"✗ Errore: {e.user_message}", Qgis.Warning)
            return False
        except EnviDataError as e:
            self.message = e.user_message
            source_info = f" (sorgente: {e.source})" if e.source else ""
            task_log(f"✗ Errore dati{source_info}: {e.user_message}", Qgis.Warning)
            return not e.recoverable  # Return True if recoverable
        except EnviError as e:
            self.message = e.user_message
            task_log(f"✗ Errore: {e.user_message}", Qgis.Warning if not e.recoverable else Qgis.Warning)
            return e.recoverable
        except Exception as e:
            self.message = f"Errore imprevisto: {str(e)}"
            task_log(self.message, Qgis.Warning)
            return False

