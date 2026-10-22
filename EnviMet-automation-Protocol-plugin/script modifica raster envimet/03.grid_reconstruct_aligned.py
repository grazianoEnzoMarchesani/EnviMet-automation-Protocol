import os
from qgis.core import (
    QgsProject,
    QgsGeometry,
    QgsFeature,
    QgsVectorLayer,
    QgsRectangle,
    QgsVectorFileWriter
)
from qgis.utils import iface

def generate_and_save_aligned_grid():
    # 1. Verifica dello stato del progetto e recupero del path
    project = QgsProject.instance()
    project_path = project.fileName()
    
    if not project_path:
        print("Errore critico: Il progetto QGIS corrente non è salvato. Salva prima il progetto.")
        return
        
    project_dir = os.path.dirname(project_path)
    output_path = os.path.join(project_dir, "griglia_totale_sovrapponibile.gpkg")

    # 2. Validazione del layer sorgente
    layer = iface.activeLayer()
    if not layer or not layer.isSpatial():
        print("Errore: Seleziona il layer della griglia incompleta come layer attivo.")
        return

    extent = layer.extent()
    features = list(layer.getFeatures())
    if len(features) == 0:
        print("Errore: Il layer attivo non contiene feature.")
        return

    # 3. Estrazione passo nativo (dx, dy) dalla prima feature utile
    first_geom = features[0].geometry()
    bbox = first_geom.boundingBox()
    dx = bbox.width()
    dy = bbox.height()

    if dx <= 0 or dy <= 0:
        print("Errore: Impossibile determinare le dimensionsi nominali della cella.")
        return

    # 4. Ancoraggio geometrico rigido sul pivot esistente
    pivot_box = first_geom.boundingBox()
    pivot_xmin = pivot_box.xMinimum()
    pivot_ymin = pivot_box.yMinimum()

    ext_xmin = extent.xMinimum()
    ext_xmax = extent.xMaximum()
    ext_ymin = extent.yMinimum()
    ext_ymax = extent.yMaximum()

    # Ricalcolo dei confini del bounding box per perfetto allineamento dei nodi
    grid_xmin = pivot_xmin - (int(round((pivot_xmin - ext_xmin) / dx)) * dx)
    grid_xmax = pivot_xmin + (int(round((ext_xmax - pivot_xmin) / dx)) * dx)
    grid_ymin = pivot_ymin - (int(round((pivot_ymin - ext_ymin) / dy)) * dy)
    grid_ymax = pivot_ymin + (int(round((ext_ymax - pivot_ymin) / dy)) * dy)

    cols = int(round((grid_xmax - grid_xmin) / dx))
    rows = int(round((grid_ymax - grid_ymin) / dy))

    print(f"Directory di output: {project_dir}")
    print(f"Matrice da generare: {cols} colonne x {rows} righe")

    # 5. Creazione del layer temporaneo in memoria (struttura dati)
    crs_auth = layer.crs().authid()
    mem_layer = QgsVectorLayer(f"Polygon?crs={crs_auth}", "Griglia_Temp", "memory")
    mem_provider = mem_layer.dataProvider()
    
    new_features = []

    # 6. Generazione vettoriale procedurale
    for i in range(cols):
        for j in range(rows):
            c_xmin = grid_xmin + (i * dx)
            c_xmax = c_xmin + dx
            c_ymin = grid_ymin + (j * dy)
            c_ymax = c_ymin + dy
            
            rect = QgsRectangle(c_xmin, c_ymin, c_xmax, c_ymax)
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromRect(rect))
            new_features.append(feat)

    if not new_features:
        print("Nessuna feature generata.")
        return

    mem_provider.addFeatures(new_features)
    mem_layer.updateExtents()

    # 7. Scrittura fisica su disco tramite QgsVectorFileWriter con gestione dinamica dell'unpacking
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "griglia_ricostruita"
    
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        mem_layer,
        output_path,
        project.transformContext(),
        options
    )

    # Gestione dinamica dell'output (accetta tuple a 2, 3 o più elementi senza fallire)
    if isinstance(result, tuple):
        error = result[0]
        error_string = result[1] if len(result) > 1 else "Errore sconosciuto"
    else:
        # Se l'API restituisce un codice di errore atomico (fallback estremo)
        error = result
        error_string = "Errore non documentato"

    if error == QgsVectorFileWriter.NoError:
        # 8. Caricamento del file generato nel pannello Layer di QGIS
        final_layer = QgsVectorLayer(f"{output_path}|layername=griglia_ricostruita", "Griglia Totale Esportata", "ogr")
        if final_layer.isValid():
            project.addMapLayer(final_layer)
            print(f"Successo: File salvato e caricato correttamente in: {output_path}")
        else:
            print("Errore nel caricamento del file salvato su disco.")
    else:
        print(f"Errore di scrittura del file: {error_string}")

# Esecuzione
generate_and_save_aligned_grid()