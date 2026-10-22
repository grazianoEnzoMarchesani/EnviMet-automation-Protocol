import processing
import os
import csv
import re
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                                 QPushButton, QProgressBar, QMessageBox, QFileDialog)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsFeatureRequest,
    QgsSpatialIndex, QgsCoordinateTransform, QgsFeature, QgsPointXY
)

class EstrazioneMLDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Generatore Dataset ML (Manuale per quota)")
        self.resize(500, 450)
        self.resize(500, 550)
        layout = QVBoxLayout()
        
        self.info = QLabel("Seleziona manualmente le coppie di layer per una quota alla volta.\n"
                           "Lo script unirà i dati per vicinanza spaziale (Spatial Join).")
        self.info.setStyleSheet("color: blue; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(self.info)

        self.lbl_aeris = QLabel("1. Layer Vento AERIS (es. aeris_vettoriale...):")
        self.cb_aeris = QComboBox()
        layout.addWidget(self.lbl_aeris)
        layout.addWidget(self.cb_aeris)

        self.cb_aeris_field = QComboBox()
        layout.addWidget(QLabel("   -> Campo Velocità Vento AERIS (es. u_aeris_base):"))
        layout.addWidget(self.cb_aeris_field)

        self.lbl_envi = QLabel("2. Layer Vento ENVI-met (es. Griglia_Statistiche...):")
        self.cb_envi = QComboBox()
        layout.addWidget(self.lbl_envi)
        layout.addWidget(self.cb_envi)
        
        self.cb_envi_field = QComboBox()
        layout.addWidget(QLabel("   -> Campo Velocità Vento ENVI-met (es. Median_median):"))
        layout.addWidget(self.cb_envi_field)

        self.lbl_bld = QLabel("3. Layer Vettoriale Edifici (Impronte):")
        self.cb_bld = QComboBox()
        self.cb_bld.currentIndexChanged.connect(self.update_fields)
        layout.addWidget(self.lbl_bld)
        layout.addWidget(self.cb_bld)
        
        self.lbl_field = QLabel("   -> Campo Altezza Edifici:")
        self.cb_field = QComboBox()
        layout.addWidget(self.lbl_field)
        layout.addWidget(self.cb_field)
        
        self.lbl_svf = QLabel("4. Raster Sky View Factor (SVF):")
        self.cb_svf = QComboBox()
        layout.addWidget(self.lbl_svf)
        layout.addWidget(self.cb_svf)
        
        self.lbl_veg = QLabel("5. Raster Canopy Alberi (Opzionale):")
        self.cb_veg = QComboBox()
        self.cb_veg.addItem("-- Nessuno --", None)
        layout.addWidget(self.lbl_veg)
        layout.addWidget(self.cb_veg)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.btn_run = QPushButton("Estrai Statistiche ed Esporta CSV")
        self.btn_run.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
        self.btn_run.clicked.connect(self.run_extraction)
        layout.addWidget(self.btn_run)

        self.setLayout(layout)
        self.populate_combos()
        
        self.cb_aeris.currentIndexChanged.connect(self.update_aeris_fields)
        self.cb_envi.currentIndexChanged.connect(self.update_envi_fields)
        self.update_aeris_fields()
        self.update_envi_fields()

    def populate_combos(self):
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                self.cb_aeris.addItem(layer.name(), layer.id())
                self.cb_envi.addItem(layer.name(), layer.id())
                self.cb_bld.addItem(layer.name(), layer.id())
            elif isinstance(layer, QgsRasterLayer):
                self.cb_svf.addItem(layer.name(), layer.id())
                self.cb_veg.addItem(layer.name(), layer.id())
        self.update_fields()

    def update_aeris_fields(self):
        self.cb_aeris_field.clear()
        layer = QgsProject.instance().mapLayer(self.cb_aeris.currentData())
        if layer:
            for field in layer.fields():
                self.cb_aeris_field.addItem(field.name())

    def update_envi_fields(self):
        self.cb_envi_field.clear()
        layer = QgsProject.instance().mapLayer(self.cb_envi.currentData())
        if layer:
            for field in layer.fields():
                self.cb_envi_field.addItem(field.name())

    def update_fields(self):
        self.cb_field.clear()
        if not self.cb_bld.currentData(): return
        layer = QgsProject.instance().mapLayer(self.cb_bld.currentData())
        if not layer: return
        
        for field in layer.fields():
            if field.isNumeric():
                self.cb_field.addItem(field.name())
        
        for i in range(self.cb_field.count()):
            text = self.cb_field.itemText(i).lower()
            if 'height' in text or 'altezza' in text or 'h_ost' in text:
                self.cb_field.setCurrentIndex(i)
                break

    def run_extraction(self):
        if not self.cb_aeris.currentData() or not self.cb_envi.currentData() or not self.cb_svf.currentData() or not self.cb_bld.currentData():
            QMessageBox.warning(self, "Attenzione", "Compila tutti i campi obbligatori.")
            return

        aeris_layer = QgsProject.instance().mapLayer(self.cb_aeris.currentData())
        envi_layer = QgsProject.instance().mapLayer(self.cb_envi.currentData())
        bld_layer = QgsProject.instance().mapLayer(self.cb_bld.currentData())
        svf_layer = QgsProject.instance().mapLayer(self.cb_svf.currentData())
        veg_layer = QgsProject.instance().mapLayer(self.cb_veg.currentData()) if self.cb_veg.currentData() else None
        h_field = self.cb_field.currentText()

        path, _ = QFileDialog.getSaveFileName(self, "Salva Dataset CSV", 
                                              "dataset_quota.csv", "CSV Files (*.csv)")
        if not path:
            return

        self.btn_run.setEnabled(False)
        self.progress_bar.setValue(10)

        try:
            # Crea un clone del layer AERIS per calcolare le morfologie
            clone_layer = aeris_layer.materialize(QgsFeatureRequest())
            clone_layer.setName(aeris_layer.name() + "_ML")

            # 1. Join By Location Summary
            join_result = processing.run("qgis:joinbylocationsummary", {
                'INPUT': clone_layer,
                'JOIN': bld_layer,
                'PREDICATE': [0],
                'JOIN_FIELDS': [h_field],
                'SUMMARIES': [8], # stdev
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            temp_layer = join_result['OUTPUT']
            self.progress_bar.setValue(40)

            # 2. SVF
            processing.run("qgis:zonalstatistics", {
                'INPUT_RASTER': svf_layer.source(), 'RASTER_BAND': 1,
                'INPUT_VECTOR': temp_layer, 'COLUMN_PREFIX': 'ml_svf_', 'STATISTICS': [2]
            })
            self.progress_bar.setValue(70)

            # 3. Veg
            if veg_layer:
                processing.run("qgis:zonalstatistics", {
                    'INPUT_RASTER': veg_layer.source(), 'RASTER_BAND': 1,
                    'INPUT_VECTOR': temp_layer, 'COLUMN_PREFIX': 'ml_veg_', 'STATISTICS': [2]
                })
            self.progress_bar.setValue(90)

            # Estrai z_target dal nome del layer AERIS
            match = re.search(r'(\d+\.?\d*)[mM]?$', aeris_layer.name().replace('_', ''))
            z_target = float(match.group(1)) if match else 0.0

            # Pre-carica i dati ENVI-met in un dizionario mappato su 'fid' (se non c'è fid, usa l'ID della feature)
            # Inizializziamo l'indice spaziale per ENVI-met
            print("Costruzione indice spaziale per ENVI-met...")
            envi_idx = QgsSpatialIndex()
            envi_feats = {}
            envi_col = self.cb_envi_field.currentText()
            
            crs_envi = envi_layer.crs()
            crs_aeris = temp_layer.crs()
            transform = None
            if crs_envi != crs_aeris:
                transform = QgsCoordinateTransform(crs_envi, crs_aeris, QgsProject.instance())

            for feat in envi_layer.getFeatures():
                geom = feat.geometry()
                if transform:
                    geom.transform(transform)
                    feat_to_add = QgsFeature(feat.id())
                    feat_to_add.setGeometry(geom)
                    envi_idx.addFeature(feat_to_add)
                else:
                    envi_idx.addFeature(feat)
                
                val = feat[envi_col] if envi_col else None
                envi_feats[feat.id()] = val

            # Identifica le colonne nel layer risultante (basato su AERIS)
            fields = [f.name() for f in temp_layer.fields()]
            h_ost_col = next((f for f in fields if 'h_ost' in f.lower() and 'mean' in f.lower()), None)
            lambda_col = next((f for f in fields if 'lambda' in f.lower() or 'den_' in f.lower()), None)
            
            u_aeris_col = self.cb_aeris_field.currentText()
            
            svf_col = next((f for f in fields if 'ml_svf_' in f.lower()), None)
            veg_col = next((f for f in fields if 'ml_veg_' in f.lower()), None)
            hstd_col = next((f for f in fields if h_field.lower() in f.lower() and ('std' in f.lower() or 'dev' in f.lower())), None)
            if not hstd_col: hstd_col = next((f for f in fields if 'stdev' in f.lower() or 'std' in f.lower()), None)
            
            fid_aeris_col = next((f for f in fields if f.lower() == 'fid'), None)

            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                headers = ['fid', 'z_target', 'h_ost', 'lambda_p', 'u_aeris', 'u_envimet', 'svf_mean', 'h_std', 'veg_mean']
                writer.writerow(headers)
                
                valid_points = 0
                for feat in temp_layer.getFeatures():
                    fid_val = feat[fid_aeris_col] if fid_aeris_col else feat.id()
                    
                    # Cerca il punto ENVI-met più vicino (Spatial Join)
                    pt = feat.geometry().centroid().asPoint()
                    nearest_ids = envi_idx.nearestNeighbor(QgsPointXY(pt), 1)
                    
                    if not nearest_ids:
                        continue # Nessun punto ENVI-met trovato nelle vicinanze (fuori griglia)
                        
                    # Controlla la distanza reale per sicurezza (se è troppo lontano, ignora)
                    envi_closest_feat = envi_layer.getFeature(nearest_ids[0])
                    geom_envi = envi_closest_feat.geometry()
                    if transform:
                        geom_envi.transform(transform)
                    dist = feat.geometry().distance(geom_envi)
                    
                    if dist > 10.0: # Soglia di sicurezza di 10 metri
                        continue
                        
                    u_e = envi_feats.get(nearest_ids[0])
                    if u_e is None or float(u_e) == 0.0:
                        continue # Punto nullo in ENVI-met
                        
                    u_a = feat[u_aeris_col] if u_aeris_col and feat[u_aeris_col] is not None else 0.0
                    
                    h_ost = feat[h_ost_col] if h_ost_col and feat[h_ost_col] is not None else 0.0
                    lp = feat[lambda_col] if lambda_col and feat[lambda_col] is not None else 0.0
                    svf = feat[svf_col] if svf_col and feat[svf_col] is not None else 1.0
                    hstd = feat[hstd_col] if hstd_col and feat[hstd_col] is not None else 0.0
                    veg = feat[veg_col] if veg_col and feat[veg_col] is not None else 0.0
                    
                    writer.writerow([fid_val, z_target, h_ost, lp, u_a, u_e, svf, hstd, veg])
                    valid_points += 1

            QMessageBox.information(self, "Completato", f"CSV esportato con successo in:\n{path}\n\nPunti validi estratti (sovrapposti): {valid_points}")

        except Exception as e:
            QMessageBox.critical(self, "Errore", f"L'estrazione ha fallito:\n{str(e)}")
            
        finally:
            self.progress_bar.setValue(100)
            self.btn_run.setEnabled(True)

dlg = EstrazioneMLDialog()
dlg.show()
