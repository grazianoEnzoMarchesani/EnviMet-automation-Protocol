import os
import numpy as np
from osgeo import gdal
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsFeatureRequest,
    QgsVectorFileWriter,
    QgsProcessingUtils
)
import processing

def aggregate_and_zone_statistics():
    project = QgsProject.instance()
    project_dir = project.absolutePath()
    
    if not project_dir:
        QMessageBox.critical(
            None, 
            "Errore di Persistenza", 
            "Il progetto QGIS corrente deve essere salvato su disco prima dell'esecuzione."
        )
        return

    layers = project.mapLayers().values()
    vector_layers = [l for l in layers if isinstance(l, QgsVectorLayer)]
    
    if not vector_layers:
        QMessageBox.critical(None, "Errore", "Nessun layer vettoriale caricato.")
        return
        
    vector_names = [l.name() for l in vector_layers]
    selected_name, ok = QInputDialog.getItem(
        None, "Seleziona Griglia", "Scegli il layer vettoriale di destinazione:", vector_names, 0, False
    )
    
    if not ok or not selected_name:
        return
        
    grid_layer = vector_layers[vector_names.index(selected_name)]
    
    height_strata = ["0.0m-3.0m", "3.0m-6.0m", "6.0m-9.0m", "9.0m-12.0m", "12.0m-15.0m"]
    raster_groups = {h: [] for h in height_strata}
    
    raster_layers = [l for l in layers if isinstance(l, QgsRasterLayer)]
    
    for r_layer in raster_layers:
        for h in height_strata:
            if h in r_layer.name():
                raster_groups[h].append(r_layer)
                break

    total_found = sum(len(v) for v in raster_groups.values())
    if total_found == 0:
        QMessageBox.warning(None, "Output", "Nessun raster corrispondente ai pattern individuato.")
        return

    for height, r_list in raster_groups.items():
        if not r_list:
            continue
            
        print(f"Processing strato: {height} ({len(r_list)} layer individuati)...")
        
        spatial_domains = {}
        
        for r in r_list:
            ds = gdal.Open(r.source())
            if ds is None:
                continue
            gt = ds.GetGeoTransform()
            spatial_key = (round(gt[0], 0), round(gt[3], 0))
            
            if spatial_key not in spatial_domains:
                spatial_domains[spatial_key] = []
            spatial_domains[spatial_key].append((r, ds.RasterXSize, ds.RasterYSize, gt))
            ds = None

        mean_vrt_inputs = []
        median_vrt_inputs = []
        domain_idx = 0
        
        for spatial_key, domain_rasters in spatial_domains.items():
            min_cols = min([dr[1] for dr in domain_rasters])
            min_rows = min([dr[2] for dr in domain_rasters])
            reference_geo_transform = domain_rasters[0][3]
            
            first_raster = domain_rasters[0][0]
            provider = first_raster.dataProvider()
            crs = first_raster.crs().toWkt()
            no_data_val = provider.sourceNoDataValue(1)
            
            stack = []
            for r_data in domain_rasters:
                ds = gdal.Open(r_data[0].source())
                band = ds.GetRasterBand(1)
                arr = band.ReadAsArray(0, 0, min_cols, min_rows).astype(np.float32)
                if no_data_val is not None:
                    arr[arr == no_data_val] = np.nan
                stack.append(arr)
                ds = None
                
            np_stack = np.array(stack)
            mean_arr = np.nanmean(np_stack, axis=0)
            median_arr = np.nanmedian(np_stack, axis=0)
            
            def array_to_project_raster(array, name_suffix):
                fn = os.path.join(project_dir, f"{name_suffix}_{domain_idx}.tif")
                out_ds = gdal.GetDriverByName('GTiff').Create(fn, min_cols, min_rows, 1, gdal.GDT_Float32)
                out_ds.SetGeoTransform(reference_geo_transform)
                out_ds.SetProjection(crs)
                band = out_ds.GetRasterBand(1)
                band.WriteArray(array)
                if no_data_val is not None:
                    band.SetNoDataValue(no_data_val)
                out_ds.FlushCache()
                out_ds = None
                return fn

            mean_vrt_inputs.append(array_to_project_raster(mean_arr, f"mean_{height}"))
            median_vrt_inputs.append(array_to_project_raster(median_arr, f"median_{height}"))
            domain_idx += 1

        mean_vrt_path = os.path.join(project_dir, f"mean_{height}_mosaic.vrt")
        median_vrt_path = os.path.join(project_dir, f"median_{height}_mosaic.vrt")
        
        gdal.BuildVRT(mean_vrt_path, mean_vrt_inputs)
        gdal.BuildVRT(median_vrt_path, median_vrt_inputs)
        
        output_vector_layer = grid_layer.materialize(QgsFeatureRequest())
        
        params_mean = {
            'INPUT_VECTOR': output_vector_layer,
            'INPUT_RASTER': mean_vrt_path,
            'RASTER_BAND': 1,
            'COLUMN_PREFIX': 'Mean_',
            'STATISTICS': [2]
        }
        processing.run("native:zonalstatistics", params_mean)
        
        params_median = {
            'INPUT_VECTOR': output_vector_layer,
            'INPUT_RASTER': median_vrt_path,
            'RASTER_BAND': 1,
            'COLUMN_PREFIX': 'Median_',
            'STATISTICS': [3]
        }
        processing.run("native:zonalstatistics", params_median)
        
        # 5. I/O Nativo e Sanitizzazione Variabili per OGR/SQLite
        safe_height = height.replace(".", "_").replace("-", "_").replace("m", "")
        table_name = f"Griglia_Statistiche_{safe_height}"
        
        gpkg_path = os.path.normpath(os.path.join(project_dir, f"{table_name}.gpkg")).replace("\\", "/")
        
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = table_name
        
        # Correzione Unpacking: l'operatore *_ assorbe i percorsi di ritorno aggiuntivi (newFilename, newLayer)
        error, error_msg, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(
            output_vector_layer,
            gpkg_path,
            project.transformContext(),
            options
        )
        
        if error != QgsVectorFileWriter.NoError:
            print(f"Errore I/O OGR fatale in fase di scrittura: {error_msg}")
            continue
            
        uri = f"{gpkg_path}|layername={table_name}"
        final_gpkg_layer = QgsVectorLayer(uri, f"Griglia_Statistiche_{height}", "ogr")
        
        if final_gpkg_layer.isValid():
            project.addMapLayer(final_gpkg_layer)
        else:
            print(f"Errore: Il provider non è riuscito a validare il file OGR al percorso {uri}")
        
    print("Processing multicriterio completato.")

aggregate_and_zone_statistics()