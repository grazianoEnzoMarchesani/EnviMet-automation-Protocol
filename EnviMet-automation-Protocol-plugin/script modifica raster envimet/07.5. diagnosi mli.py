"""
Script QGIS per diagnosi COMPLETA del problema R².
Confronta: (1) u_z dalla web app vs ENVI-met, (2) Predizione Python diretta vs ENVI-met.
Da eseguire nella console Python di QGIS.
"""
import math
import re
import numpy as np
from qgis.core import (
    QgsProject, QgsSpatialIndex, QgsPointXY, QgsCoordinateTransform, QgsFeature
)
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox, QListWidget, QAbstractItemView
)

# Prova a caricare il modello ML Python
from qgis.PyQt.QtWidgets import QFileDialog
import os

MODEL_PATH = '/Users/grazianoenzomarchesani/Documents/GitHub/aeris/anemometro/assets/scripts/aeris_ml_model_3d.joblib'
# Se il percorso non esiste (es. siamo su Windows), chiediamo all'utente
if not os.path.exists(MODEL_PATH):
    # Prova a indovinare un percorso relativo o comune su Windows
    win_path = r"C:\Users\Graziano\Documents\GitHub\aeris\anemometro\assets\scripts\aeris_ml_model_3d.joblib"
    if os.path.exists(win_path):
        MODEL_PATH = win_path
    else:
        # Mostriamo un file dialog per selezionare il modello
        filename, _ = QFileDialog.getOpenFileName(None, "Seleziona aeris_ml_model_3d.joblib", "", "Joblib Files (*.joblib)")
        if filename:
            MODEL_PATH = filename

try:
    import joblib
    ml_model = joblib.load(MODEL_PATH)
    HAS_MODEL = True
    print(f"✅ Modello Python caricato: {ml_model.n_features_in_} features, {len(ml_model._predictors)} alberi")
except Exception as e:
    HAS_MODEL = False
    print(f"⚠️ Modello Python non caricabile: {e}")
    print("   Lo script funzionerà comunque per il confronto u_z vs ENVI-met")

class DiagnosiMLDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔍 DIAGNOSI ML - Confronto R² (v2.0)")
        self.resize(500, 550)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("1. Layer ML (web app export con u_z):"))
        self.list_ml = QListWidget()
        self.list_ml.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_ml)
        
        self.cb_ml_field = QComboBox()
        layout.addWidget(QLabel("Campo u_z (predizione ML):"))
        layout.addWidget(self.cb_ml_field)
        
        layout.addWidget(QLabel("2. Layer ENVI-met (ground truth):"))
        self.list_envi = QListWidget()
        self.list_envi.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_envi)
        
        self.cb_envi_field = QComboBox()
        layout.addWidget(QLabel("Campo velocità ENVI-met:"))
        layout.addWidget(self.cb_envi_field)
        
        self.btn_run = QPushButton("🔍 Esegui Diagnosi Completa")
        self.btn_run.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px;")
        self.btn_run.clicked.connect(self.run_diagnosis)
        layout.addWidget(self.btn_run)
        
        self.setLayout(layout)
        self.populate_layers()
        self.list_ml.itemSelectionChanged.connect(self.update_ml_fields)
        self.list_envi.itemSelectionChanged.connect(self.update_envi_fields)

    def populate_layers(self):
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == layer.VectorLayer:
                self.list_ml.addItem(layer.name())
                self.list_ml.item(self.list_ml.count()-1).setData(32, layer.id())
                self.list_envi.addItem(layer.name())
                self.list_envi.item(self.list_envi.count()-1).setData(32, layer.id())

    def update_ml_fields(self):
        self.cb_ml_field.clear()
        selected = self.list_ml.selectedItems()
        if not selected: return
        layer = QgsProject.instance().mapLayer(selected[0].data(32))
        if layer:
            for field in layer.fields():
                if field.isNumeric():
                    self.cb_ml_field.addItem(field.name())
            # Auto-select u_z
            idx = self.cb_ml_field.findText('u_z')
            if idx >= 0: self.cb_ml_field.setCurrentIndex(idx)

    def update_envi_fields(self):
        self.cb_envi_field.clear()
        selected = self.list_envi.selectedItems()
        if not selected: return
        layer = QgsProject.instance().mapLayer(selected[0].data(32))
        if layer:
            for field in layer.fields():
                if field.isNumeric():
                    self.cb_envi_field.addItem(field.name())

    def get_ml_features_from_layer(self, feat, z_target):
        """Estrae le 8 features ML direttamente dal layer, come fa map_gis.js"""
        def get_prop(key):
            key_low = key.lower()
            for field_name in [f.name() for f in feat.fields()]:
                if field_name.lower() == key_low or key_low in field_name.lower():
                    val = feat[field_name]
                    if val is not None and val != '':
                        return float(val)
            return None

        h_ost = get_prop('h_ost_mean') or get_prop('h_ost') or 0.0
        lambda_p = get_prop('lambda_p') or get_prop('den_mean') or get_prop('Phi_mac') or 0.25
        svf = get_prop('svf_mean') or 0.5
        h_std = get_prop('h_ost_stde') or get_prop('h_std') or 0.0
        veg = get_prop('veg_mean') or 0.0
        
        h_ost_safe = max(h_ost, 0.1)
        z_su_h = z_target / h_ost_safe
        is_below = 1 if z_target <= h_ost else 0
        
        return [z_target, h_ost, lambda_p, z_su_h, is_below, svf, h_std, veg]

    def run_diagnosis(self):
        selected_ml = self.list_ml.selectedItems()
        selected_envi = self.list_envi.selectedItems()
        
        if not selected_ml or not selected_envi:
            QMessageBox.warning(self, "Attenzione", "Seleziona almeno un layer per parte.")
            return
            
        ml_field = self.cb_ml_field.currentText()
        envi_field = self.cb_envi_field.currentText()
        
        print("\n" + "=" * 70)
        print("🔍 DIAGNOSI COMPLETA ML")
        print(f"   Campo ML selezionato: '{ml_field}'")
        print(f"   Campo ENVI selezionato: '{envi_field}'")
        print("=" * 70)
        
        y_true_all = []
        y_pred_webapp_all = []  # u_z dalla web app
        y_pred_python_all = []  # predizione Python diretta
        
        num_pairs = min(len(selected_ml), len(selected_envi))
        
        for i in range(num_pairs):
            ml_layer = QgsProject.instance().mapLayer(selected_ml[i].data(32))
            envi_layer = QgsProject.instance().mapLayer(selected_envi[i].data(32))
            
            # Determina z_target dal nome del layer
            match = re.search(r'(\d+\.?\d*)', ml_layer.name())
            z_target = float(match.group(1)) if match else 1.5
            
            print(f"\n--- Coppia {i+1}: {ml_layer.name()} | {envi_layer.name()} (z={z_target}) ---")
            
            # Stampa le colonne disponibili nel layer ML
            ml_fields_list = [f.name() for f in ml_layer.fields()]
            print(f"  Colonne ML: {ml_fields_list}")
            
            # CRS
            crs_ml = ml_layer.crs()
            crs_envi = envi_layer.crs()
            transform = None
            if crs_ml != crs_envi:
                transform = QgsCoordinateTransform(crs_ml, crs_envi, QgsProject.instance())
                print(f"  ⚠️ CRS diversi: ML={crs_ml.authid()} ENVI={crs_envi.authid()} → trasformazione applicata")
            else:
                print(f"  CRS: {crs_ml.authid()} (uguale)")
            
            # Indice spaziale ML
            ml_idx = QgsSpatialIndex()
            ml_feats_val = {}
            ml_feats_obj = {}
            for f in ml_layer.getFeatures():
                if transform:
                    geom = f.geometry()
                    geom.transform(transform)
                    feat_add = QgsFeature(f.id())
                    feat_add.setGeometry(geom)
                    ml_idx.addFeature(feat_add)
                else:
                    ml_idx.addFeature(f)
                ml_feats_val[f.id()] = f[ml_field]
                ml_feats_obj[f.id()] = f  # salva l'intera feature per estrarre ML features
            
            # Match spaziale
            print(f"  Totale features ML: {ml_layer.featureCount()}")
            print(f"  Totale features ENVI: {envi_layer.featureCount()}")
            
            samples_printed = 0
            punti = 0
            distances_coppia = []
            for e_feat in envi_layer.getFeatures():
                pt = e_feat.geometry().centroid().asPoint()
                nearest_ids = ml_idx.nearestNeighbor(QgsPointXY(pt), 1)
                
                if not nearest_ids:
                    continue
                    
                ml_val = ml_feats_val.get(nearest_ids[0])
                envi_val = e_feat[envi_field]
                
                if ml_val is None or envi_val is None:
                    continue
                    
                ml_val_f = float(ml_val)
                envi_val_f = float(envi_val)
                
                if envi_val_f == 0.0 and ml_val_f == 0.0:
                    continue
                
                y_true_all.append(envi_val_f)
                y_pred_webapp_all.append(ml_val_f)
                
                # Calcola distanza
                ml_feat = ml_feats_obj.get(nearest_ids[0])
                dist = -1
                if ml_feat:
                    geom_ml = ml_feat.geometry()
                    if transform:
                        geom_ml.transform(transform)
                    dist = pt.distance(geom_ml.centroid().asPoint())
                    distances_coppia.append(dist)
                
                # Predizione Python diretta
                if HAS_MODEL:
                    if ml_feat:
                        features = self.get_ml_features_from_layer(ml_feat, z_target)
                        try:
                            import pandas as pd
                            X = pd.DataFrame([features], columns=['z_target', 'h_ost', 'lambda_p', 'z_su_h', 'is_below_canopy', 'svf_mean', 'h_std', 'veg_mean'])
                            py_pred = ml_model.predict(X)[0]
                        except:
                            X_arr = np.array([features])
                            py_pred = ml_model.predict(X_arr)[0]
                        y_pred_python_all.append(py_pred)
                        
                        # Stampa i primi 3 campioni per diagnosi
                        if samples_printed < 3:
                            print(f"\n  📋 Campione {samples_printed+1}:")
                            print(f"     Distanza spaziale di match: {dist:.2f} metri")
                            print(f"     Features ML: {[round(x,3) for x in features]}")
                            print(f"     u_z webapp (JS): {ml_val_f:.3f}")
                            print(f"     Pred Python:     {py_pred:.3f}")
                            print(f"     ENVI-met truth:  {envi_val_f:.3f}")
                            print(f"     Δ webapp-ENVI:   {abs(ml_val_f - envi_val_f):.3f}")
                            print(f"     Δ python-ENVI:   {abs(py_pred - envi_val_f):.3f}")
                            samples_printed += 1
                
                punti += 1
            
            print(f"  Punti validi: {punti}")
            if distances_coppia:
                print(f"  Distanza match: media={np.mean(distances_coppia):.2f}m, max={np.max(distances_coppia):.2f}m")
        
        # Calcolo R²
        n = len(y_true_all)
        if n == 0:
            QMessageBox.warning(self, "Errore", "Nessun punto valido trovato.")
            return
        
        mean_y = sum(y_true_all) / n
        ss_tot = sum((y - mean_y)**2 for y in y_true_all)
        
        # R² webapp (u_z dalla web app)
        ss_res_webapp = sum((yt - yp)**2 for yt, yp in zip(y_true_all, y_pred_webapp_all))
        r2_webapp = 1 - (ss_res_webapp / ss_tot) if ss_tot != 0 else 0
        rmse_webapp = math.sqrt(ss_res_webapp / n)
        
        msg = f"\n{'='*70}\n"
        msg += f"📊 RISULTATI DIAGNOSI ({n} punti su {num_pairs} coppie)\n"
        msg += f"{'='*70}\n\n"
        msg += f"A) u_z dalla Web App vs ENVI-met:\n"
        msg += f"   R² = {r2_webapp:.4f}  |  RMSE = {rmse_webapp:.4f} m/s\n\n"
        
        if HAS_MODEL and len(y_pred_python_all) == n:
            ss_res_python = sum((yt - yp)**2 for yt, yp in zip(y_true_all, y_pred_python_all))
            r2_python = 1 - (ss_res_python / ss_tot) if ss_tot != 0 else 0
            rmse_python = math.sqrt(ss_res_python / n)
            
            # Confronto webapp vs python
            ss_res_jsvspy = sum((yw - yp)**2 for yw, yp in zip(y_pred_webapp_all, y_pred_python_all))
            r2_jsvspy = 1 - (ss_res_jsvspy / sum((y - sum(y_pred_webapp_all)/n)**2 for y in y_pred_webapp_all)) if ss_tot != 0 else 0
            
            msg += f"B) Predizione Python diretta vs ENVI-met:\n"
            msg += f"   R² = {r2_python:.4f}  |  RMSE = {rmse_python:.4f} m/s\n\n"
            msg += f"C) u_z Web App vs Pred Python (coerenza JS↔Python):\n"
            msg += f"   R² = {r2_jsvspy:.4f}\n\n"
            
            if r2_python < 0.8:
                msg += f"⚠️ DIAGNOSI: R² Python ({r2_python:.4f}) basso!\n"
                msg += f"   Le features di hugePescara_ready NON corrispondono\n"
                msg += f"   ai dati di training. Il modello va RIADDESTRATO\n"
                msg += f"   sulle features del GeoJSON attuale.\n"
            elif r2_webapp < 0.8 and r2_python > 0.8:
                msg += f"⚠️ DIAGNOSI: Il modello Python va bene ({r2_python:.4f})\n"
                msg += f"   ma il JS diverge ({r2_webapp:.4f}). Problema nell'export JS.\n"
            else:
                msg += f"✅ DIAGNOSI: Tutto OK! R² Python = {r2_python:.4f}\n"
        
        print(msg)
        QMessageBox.information(self, "Risultati Diagnosi", msg)

dlg = DiagnosiMLDialog()
dlg.show()
