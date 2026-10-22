import os
import xml.etree.ElementTree as ET
import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsRectangle

class ENVImetReader:
    def __init__(self):
        pass
        
    def parse_edx(self, edx_path):
        """
        Parse the .EDX (XML) file to extract grid dimensions, spacing, and variable names.
        Returns a dictionary with the metadata.
        """
        if not os.path.exists(edx_path):
            raise FileNotFoundError(f"EDX file not found: {edx_path}")
            
        tree = ET.parse(edx_path)
        root = tree.getroot()
        
        nr_xdata = int(root.findtext('.//nr_xdata', '0'))
        nr_ydata = int(root.findtext('.//nr_ydata', '0'))
        nr_zdata = int(root.findtext('.//nr_zdata', '0'))
        
        spacing_x = self._process_spacing(root.findtext('.//spacing_x', ''))
        spacing_y = self._process_spacing(root.findtext('.//spacing_y', ''))
        spacing_z = self._process_spacing(root.findtext('.//spacing_z', ''))
        
        # Compute Z centroids
        z_centroids = []
        current_h = 0.0
        for sz in spacing_z:
            z_centroids.append(current_h + (sz / 2.0))
            current_h += sz
            
        vars_text = root.findtext('.//name_variables', '')
        variable_names = [v.strip() for v in vars_text.split(',')] if vars_text else []
        nr_variables = int(root.findtext('.//nr_variables', '0'))
        
        # Georeferencing
        model_rotation = float(root.findtext('.//model_rotation', '0.0'))
        location_georef_x = float(root.findtext('.//location_georef_x', '0.0'))
        location_georef_y = float(root.findtext('.//location_georef_y', '0.0'))
        
        return {
            'nr_xdata': nr_xdata,
            'nr_ydata': nr_ydata,
            'nr_zdata': nr_zdata,
            'spacing_x': spacing_x,
            'spacing_y': spacing_y,
            'spacing_z': spacing_z,
            'z_centroids': z_centroids,
            'variable_names': variable_names,
            'nr_variables': nr_variables,
            'model_rotation': model_rotation,
            'location_georef_x': location_georef_x,
            'location_georef_y': location_georef_y
        }
        
    def _process_spacing(self, spacing_string):
        if not spacing_string:
            return []
        return [float(x.strip()) for x in spacing_string.split(',')]
        
    def get_terrain_data(self, edx_path, metadata):
        """
        Locates the corresponding _SA_ (Solar Access / Ground) EDT file to extract terrain heights.
        The terrain height is assumed to be at variable index 3 (4th variable).
        """
        # Locate _SA_ file. Normally in root_output/solaraccess/ground or similar.
        dir_name = os.path.dirname(edx_path) # e.g. output/atmosphere
        root_output_dir = os.path.dirname(dir_name) # e.g. output
        
        # Simple heuristic: find any EDT file containing '_SA_' in solaraccess
        sa_edt_file = None
        
        # Try direct root/solaraccess and root/solaraccess/ground
        for sa_sub in ['solaraccess', os.path.join('solaraccess', 'ground'), '']:
            search_path = os.path.join(root_output_dir, sa_sub)
            if os.path.exists(search_path):
                for f in os.listdir(search_path):
                    if '_SA_' in f and f.endswith('.EDT'):
                        sa_edt_file = os.path.join(search_path, f)
                        break
            if sa_edt_file:
                break

        if not sa_edt_file:
            return None
            
        return self._read_terrain_from_edt(sa_edt_file, metadata)
        
    def _read_terrain_from_edt(self, sa_edt_path, metadata):
        dim_x = metadata['nr_xdata']
        dim_y = metadata['nr_ydata']
        dim_z = metadata['nr_zdata']
        
        terrain_var_index = 3 # Hardcoded in ENVI-met for SA files
        
        # Read the full file
        data = np.fromfile(sa_edt_path, dtype=np.float32)
        
        points_2d = dim_x * dim_y
        start_idx_2d = terrain_var_index * points_2d
        end_idx_2d = start_idx_2d + points_2d
        
        if end_idx_2d <= len(data):
            terrain_data = data[start_idx_2d:end_idx_2d]
        else:
            return None
            
        return terrain_data.reshape((dim_y, dim_x))
        
    def extract_slice(self, edt_path, metadata, var_index, z_level, terrain_data=None):
        """
        Extracts a 2D slice for a specific variable and Z level.
        If terrain_data is provided, it applies the "Follow Terrain" logic.
        """
        dim_x = metadata['nr_xdata']
        dim_y = metadata['nr_ydata']
        dim_z = metadata['nr_zdata']
        total_points = dim_x * dim_y * dim_z
        
        data = np.fromfile(edt_path, dtype=np.float32)
        
        start_idx = var_index * total_points
        end_idx = start_idx + total_points
        
        if end_idx > len(data):
            raise ValueError(f"EDT file is too small for variable index {var_index}")
            
        var_data = data[start_idx:end_idx].reshape((dim_z, dim_y, dim_x))
        
        slice_data = np.zeros((dim_y, dim_x), dtype=np.float32)
        
        if terrain_data is not None:
            # Follow terrain logic
            for y in range(dim_y):
                for x in range(dim_x):
                    # terrain_height is assumed to be an integer offset in Z
                    terrain_h = int(terrain_data[y, x]) if not np.isnan(terrain_data[y, x]) else 0
                    if terrain_h == -999:
                        terrain_h = 0
                        
                    adjusted_z = min(terrain_h + z_level, dim_z - 1)
                    val = var_data[adjusted_z, y, x]
                    slice_data[y, x] = val if val != -999.0 else np.nan
        else:
            # Flat slice
            slice_data = var_data[z_level, :, :]
            slice_data = np.where(slice_data == -999.0, np.nan, slice_data)
            
        return slice_data
        
    def export_to_raster(self, data_slice, output_path, qgs_rect, crs_authid, metadata=None, sub_info=None):
        """
        Exports a 2D numpy array to a GeoTIFF using GDAL.
        Uses EDX metadata (rotation, center) for perfect alignment.
        """
        import math
        driver = gdal.GetDriverByName("GTiff")
        rows, cols = data_slice.shape
        out_ds = driver.Create(output_path, cols, rows, 1, gdal.GDT_Float32)
        
        if metadata and 'model_rotation' in metadata and sub_info and 'center_x' in sub_info:
            theta_deg = metadata['model_rotation']
            theta_rad = math.radians(theta_deg)
            
            # The absolute Center of the grid from the QGIS Sub Area feature
            center_x = sub_info['center_x']
            center_y = sub_info['center_y']
            
            spacing_x = metadata['spacing_x'][0] if metadata['spacing_x'] else 1.0
            spacing_y = metadata['spacing_y'][0] if metadata['spacing_y'] else 1.0
            
            # Compute Grid East (gt1, gt4) and Grid South (gt2, gt5) vectors
            gt1 = spacing_x * math.cos(theta_rad)
            gt4 = -spacing_x * math.sin(theta_rad)
            gt2 = -spacing_y * math.sin(theta_rad)
            gt5 = -spacing_y * math.cos(theta_rad)
            
            # The ENVI-met center is perfectly aligned with the QGIS Sub Area center
            # Top-Left is derived by moving from the Center by -cols/2 in Grid East and -rows/2 in Grid South
            gt0 = center_x - (cols / 2.0) * gt1 - (rows / 2.0) * gt2
            gt3 = center_y - (cols / 2.0) * gt4 - (rows / 2.0) * gt5
            
            out_ds.SetGeoTransform((gt0, gt1, gt2, gt3, gt4, gt5))
        else:
            # Fallback to axis-aligned bounding box
            xmin = qgs_rect.xMinimum()
            ymax = qgs_rect.yMaximum()
            pixel_width = qgs_rect.width() / cols
            pixel_height = qgs_rect.height() / rows
            out_ds.SetGeoTransform((xmin, pixel_width, 0, ymax, 0, -pixel_height))
        
        srs = osr.SpatialReference()
        srs.SetFromUserInput(crs_authid)
        out_ds.SetProjection(srs.ExportToWkt())
        
        out_band = out_ds.GetRasterBand(1)
        out_band.SetNoDataValue(np.nan)
        
        # Write data (numpy array is origin top-left usually, ENVI-met might be bottom-left)
        # ENVI-met arrays typically have origin at bottom-left.
        # We need to flip it vertically for GDAL which expects origin at top-left.
        flipped_data = np.flipud(data_slice)
        out_band.WriteArray(flipped_data)
        
        out_band.FlushCache()
        out_ds = None # Close file
        
        return output_path
