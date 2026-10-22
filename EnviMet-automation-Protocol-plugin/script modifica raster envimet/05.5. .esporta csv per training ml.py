"""
Generatore di Dataset ML coerente con il layer QGIS.
Consente di selezionare il layer ML esportato e i layer ENVI-met
per esportare i CSV con i valori esatti.
Eseguire nella console Python di QGIS.
"""
import csv
import re
import os
from qgis.core import (
    QgsProject, QgsSpatialIndex, QgsPointXY, QgsCoordinateTransform, QgsFeature
)
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox, QListWidget, QAbstractItemView, QFileDialog
)

class ExportExactDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📥 Esporta CSV per Training ML")
        self.resize(500, 500)
        
        layout = QVBoxLayout()
        
        # Select Reference Layer
        layout.addWidget(QLabel("1. Seleziona il Layer ML di Riferimento (es. verifica_huge_aeris_vettoriale_vento_1.5):"))
        self.cb_ref = QComboBox()
        layout.addWidget(self.cb_ref)
        
        # ENVI-met Layers
        layout.addWidget(QLabel("2. Seleziona i Layer Verità ENVI-met (tutte le quote):"))
        self.list_envi = QListWidget()
        self.list_envi.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_envi)
        
        self.btn_run = QPushButton("Esporta i 5 CSV di Training")
        self.btn_run.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; padding: 10px;")
        self.btn_run.clicked.connect(self.run_export)
        layout.addWidget(self.btn_run)
        
        self.setLayout(layout)
        self.populate_layers()

    def populate_layers(self):
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == layer.VectorLayer:
                # Add to ref layer if it has h_ost_mean or similar columns
                fields = [f.name().lower() for f in layer.fields()]
                if 'h_ost_mean' in fields or 'h_ost' in fields:
                    self.cb_ref.addItem(layer.name(), layer.id())
                
                # Add to ENVI list if it has median in columns
                if any('median' in f.lower() for f in fields):
                    self.list_envi.addItem(layer.name())
                    self.list_envi.item(self.list_envi.count()-1).setData(32, layer.id())

        # Select all ENVI layers by default
        for i in range(self.list_envi.count()):
            self.list_envi.item(i).setSelected(True)

    def run_export(self):
        ref_id = self.cb_ref.currentData()
        ref_layer = QgsProject.instance().mapLayer(ref_id)
        
        selected_envi = self.list_envi.selectedItems()
        
        if not ref_layer or not selected_envi:
            QMessageBox.warning(self, "Attenzione", "Seleziona il layer di riferimento e almeno un layer ENVI-met.")
            return
            
        # Chiedi cartella dove salvare i CSV
        folder = QFileDialog.getExistingDirectory(self, "Seleziona cartella dove salvare i 5 CSV di training", "")
        if not folder:
            return

        # Mappatura delle colonne di ref_layer
        fields = [f.name() for f in ref_layer.fields()]
        h_ost_col = next((f for f in fields if f.lower() == 'h_ost_mean' or f.lower() == 'h_ost'), None)
        lambda_col = next((f for f in fields if f.lower() == 'lambda_p' or f.lower() == 'den_mean' or f.lower() == 'phi_mac'), None)
        svf_col = next((f for f in fields if f.lower() == 'svf_mean'), None)
        h_std_col = next((f for f in fields if f.lower() == 'h_ost_stde' or f.lower() == 'h_std'), None)
        veg_col = next((f for f in fields if f.lower() == 'veg_mean'), None)
        u_aeris_col = next((f for f in fields if 'u_aeris_base' in f.lower() or 'u_aeris' in f.lower()), None)

        print("\n" + "="*50)
        print(f"Esportazione da Layer Riferimento: {ref_layer.name()}")
        print(f"Mappatura colonne:")
        print(f"  h_ost    -> {h_ost_col}")
        print(f"  lambda_p -> {lambda_col}")
        print(f"  svf_mean -> {svf_col}")
        print(f"  h_std    -> {h_std_col}")
        print(f"  veg_mean -> {veg_col}")
        print("="*50)

        # Costruisci indice spaziale per il layer di riferimento
        crs_ref = ref_layer.crs()
        ref_idx = QgsSpatialIndex()
        ref_feats = {}
        
        for f in ref_layer.getFeatures():
            ref_idx.addFeature(f)
            ref_feats[f.id()] = f

        # Esporta i CSV
        for item in selected_envi:
            envi_layer = QgsProject.instance().mapLayer(item.data(32))
            if not envi_layer: continue
            
            # Determina z_target dal nome del layer ENVI-met
            match = re.search(r'(\d+\.?\d*)[mM]?\-(\d+\.?\d*)[mM]?', envi_layer.name())
            if match:
                z_min, z_max = float(match.group(1)), float(match.group(2))
                z_target = (z_min + z_max) / 2.0
            else:
                z_target = 1.5
                
            csv_filename = f"{z_target}.csv"
            csv_path = os.path.join(folder, csv_filename)
            
            # Campo vento ENVI-met
            envi_field = next((f.name() for f in envi_layer.fields() if 'median' in f.name().lower()), None)
            if not envi_field:
                continue
                
            print(f"Esportando {csv_filename}...")
            
            transform = None
            if envi_layer.crs() != crs_ref:
                transform = QgsCoordinateTransform(envi_layer.crs(), crs_ref, QgsProject.instance())
                
            with open(csv_path, 'w', newline='', encoding='utf-8') as f_csv:
                writer = csv.writer(f_csv)
                writer.writerow(['fid', 'z_target', 'h_ost', 'lambda_p', 'u_aeris', 'u_envimet', 'svf_mean', 'h_std', 'veg_mean'])
                
                punti = 0
                for e_feat in envi_layer.getFeatures():
                    pt = e_feat.geometry().centroid().asPoint()
                    if transform:
                        pt_geom = e_feat.geometry()
                        pt_geom.transform(transform)
                        pt = pt_geom.centroid().asPoint()
                        
                    nearest_ids = ref_idx.nearestNeighbor(QgsPointXY(pt), 1)
                    if nearest_ids:
                        ref_feat = ref_feats.get(nearest_ids[0])
                        u_e = e_feat[envi_field]
                        
                        if ref_feat and u_e is not None and float(u_e) != 0.0:
                            h_ost = float(ref_feat[h_ost_col] or 0.0) if h_ost_col else 0.0
                            lp = float(ref_feat[lambda_col] or 0.25) if lambda_col else 0.25
                            u_a = float(ref_feat[u_aeris_col] or 0.0) if u_aeris_col else 0.0
                            svf = float(ref_feat[svf_col] or 0.5) if svf_col else 0.5
                            h_std = float(ref_feat[h_std_col] or 0.0) if h_std_col else 0.0
                            veg = float(ref_feat[veg_col] or 0.0) if veg_col else 0.0
                            
                            writer.writerow([e_feat.id(), z_target, h_ost, lp, u_a, float(u_e), svf, h_std, veg])
                            punti += 1
                            
                print(f"  Fatto! {punti} righe scritte per z={z_target}")
                
        QMessageBox.information(self, "Esportazione Completata", f"I CSV sono stati salvati in:\n{folder}\n\nOra puoi procedere al training.")
        self.accept()

dlg = ExportExactDialog()
dlg.show()
