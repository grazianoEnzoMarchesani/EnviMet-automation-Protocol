import os
import re
from qgis.core import QgsTask, QgsMessageLog, Qgis, QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import pyqtSignal

from ...core.envimet_reader import ENVImetReader

class ENVImetImportTask(QgsTask):
    """
    QgsTask for background bulk import of ENVI-met output files.
    """
    
    # Custom signals
    progressUpdated = pyqtSignal(str, int, int, int) # step_name, step_num, total_steps, percent
    taskCompleted = pyqtSignal()
    taskTerminated = pyqtSignal()
    
    def __init__(self, edt_files, variables, heights, sub_area_geom, sub_info, crs_authid, output_dir, follow_terrain=True, custom_palette=""):
        """
        :param edt_files: list of tuples (edx_path, edt_path, time_string)
        :param variables: list of tuples (var_index, var_name)
        :param heights: list of integers representing Z levels
        :param sub_area_geom: QgsGeometry of the sub-area for the bounding box
        :param sub_info: Dictionary containing sub_area rotation, width, height, etc.
        :param crs_authid: string like 'EPSG:32632'
        :param output_dir: folder where to save the generated .tif files
        """
        super().__init__("Importazione ENVI-met", QgsTask.CanCancel)
        self.edt_files = edt_files
        self.variables = variables
        self.heights = heights
        self.sub_area_geom = sub_area_geom
        self.sub_info = sub_info
        self.crs_authid = crs_authid
        self.output_dir = output_dir
        self.follow_terrain = follow_terrain
        self.custom_palette = custom_palette
        
        self.reader = ENVImetReader()
        self.error_count = 0
        self.message = ""
        self.generated_layers = []
        
    def run(self):
        try:
            total_operations = len(self.edt_files) * len(self.variables) * len(self.heights)
            current_op = 0
            
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)
                
            qgs_rect = self.sub_area_geom.boundingBox()
            
            # Group by file to read the EDT file once, then extract multiple slices
            for edx_path, edt_path, time_str in self.edt_files:
                if self.isCanceled():
                    return False
                    
                try:
                    metadata = self.reader.parse_edx(edx_path)
                    
                    terrain_data = None
                    if self.follow_terrain:
                        terrain_data = self.reader.get_terrain_data(edx_path, metadata)
                        
                    for var_index, var_name in self.variables:
                        for height_data in self.heights:
                            if isinstance(height_data, dict):
                                z_level = height_data.get("z", 0)
                                h_val = height_data.get("h_val", "N/A").replace(" ", "")
                            else:
                                z_level = height_data
                                h_val = "N/A"

                            if self.isCanceled():
                                return False
                                
                            current_op += 1
                            percent = int((current_op / total_operations) * 100)
                            safe_var_name = "".join([c if c.isalnum() else "_" for c in var_name])
                            step_name = f"Estrazione {safe_var_name} a quota Z={z_level} (T={time_str})"
                            
                            self.progressUpdated.emit(step_name, current_op, total_operations, percent)
                            
                            slice_data = self.reader.extract_slice(edt_path, metadata, var_index, z_level, terrain_data)
                            
                            sub_name = self.sub_info.get("name", "")
                            layer_prefix = f"{sub_name} " if sub_name else ""
                            z_suffix = f"={h_val}" if h_val != "N/A" else ""
                            layer_name = f"{layer_prefix}[{time_str}] {var_name} (Z={z_level}{z_suffix})"
                            
                            safe_file_name = re.sub(r'[<>:"/\\|?*]', '_', layer_name)
                            file_name = f"{safe_file_name}.tif"
                            output_path = os.path.join(self.output_dir, file_name)
                            
                            self.reader.export_to_raster(slice_data, output_path, qgs_rect, self.crs_authid, metadata, self.sub_info)
                            
                            self.generated_layers.append((output_path, layer_name))
                            
                except Exception as e:
                    self.error_count += 1
                    QgsMessageLog.logMessage(f"Errore file {edt_path}: {e}", "EnviProtocol", Qgis.Warning)
                    
            return True
        except Exception as e:
            self.message = str(e)
            QgsMessageLog.logMessage(f"Task error: {e}", "EnviProtocol", Qgis.Critical)
            return False

    def finished(self, result):
        if result:
            # Load generated layers into QGIS
            project = QgsProject.instance()
            group_name = "Risultati ENVI-met"
            root = project.layerTreeRoot()
            group = root.findGroup(group_name)
            if not group:
                group = root.insertGroup(0, group_name)
            else:
                children = root.children()
                if children and children[0] != group:
                    clone = group.clone()
                    root.insertChildNode(0, clone)
                    root.removeChildNode(group)
                    group = clone
                
            from ...core.raster_palettes import apply_envimet_palette
                
            for path, name in self.generated_layers:
                layer = QgsRasterLayer(path, name)
                if layer.isValid():
                    project.addMapLayer(layer, False)
                    group.addLayer(layer)
                    
                    # Apply scientific palette or custom override
                    apply_envimet_palette(layer, original_layer_name=name, override_palette_name=self.custom_palette)
                    
            self.taskCompleted.emit()
        else:
            self.taskTerminated.emit()
