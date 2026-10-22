import math
from qgis.core import (
    QgsProject, QgsSpatialIndex, QgsPointXY, QgsCoordinateTransform, QgsFeature
)
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox, QListWidget, QAbstractItemView
)

class VerificaCorrelazioneDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verifica Correlazione ML vs ENVI-met (Multi-Quota)")
        self.resize(500, 500)
        
        layout = QVBoxLayout()
        
        # ML Layers
        layout.addWidget(QLabel("1. Seleziona i Layer Predizione ML (puoi selezionarne più di uno):"))
        self.list_ml = QListWidget()
        self.list_ml.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_ml)
        
        self.cb_ml_field = QComboBox()
        layout.addWidget(QLabel("Campo velocità vento predetta (comune a tutti i layer):"))
        layout.addWidget(self.cb_ml_field)
        
        # ENVI-met Layers
        layout.addWidget(QLabel("2. Seleziona i Layer Verità ENVI-met (puoi selezionarne più di uno):"))
        self.list_envi = QListWidget()
        self.list_envi.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_envi)
        
        self.cb_envi_field = QComboBox()
        layout.addWidget(QLabel("Campo velocità vento ENVI-met (comune a tutti i layer):"))
        layout.addWidget(self.cb_envi_field)
        
        self.btn_run = QPushButton("Calcola R² e Statistiche Globali")
        self.btn_run.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px;")
        self.btn_run.clicked.connect(self.run_verification)
        layout.addWidget(self.btn_run)
        
        self.setLayout(layout)
        
        self.populate_layers()
        self.list_ml.itemSelectionChanged.connect(self.update_ml_fields)
        self.list_envi.itemSelectionChanged.connect(self.update_envi_fields)

    def populate_layers(self):
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == layer.VectorLayer:
                self.list_ml.addItem(layer.name())
                self.list_ml.item(self.list_ml.count()-1).setData(32, layer.id()) # Role 32 for UserData
                self.list_envi.addItem(layer.name())
                self.list_envi.item(self.list_envi.count()-1).setData(32, layer.id())

    def update_ml_fields(self):
        self.cb_ml_field.clear()
        selected_items = self.list_ml.selectedItems()
        if not selected_items: return
        
        # Popola con i campi del primo layer selezionato
        layer_id = selected_items[0].data(32)
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            for field in layer.fields():
                if field.isNumeric():
                    self.cb_ml_field.addItem(field.name())

    def update_envi_fields(self):
        self.cb_envi_field.clear()
        selected_items = self.list_envi.selectedItems()
        if not selected_items: return
        
        layer_id = selected_items[0].data(32)
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            for field in layer.fields():
                if field.isNumeric():
                    self.cb_envi_field.addItem(field.name())

    def run_verification(self):
        selected_ml_items = self.list_ml.selectedItems()
        selected_envi_items = self.list_envi.selectedItems()
        
        if not selected_ml_items or not selected_envi_items:
            QMessageBox.warning(self, "Attenzione", "Seleziona almeno un layer ML e un layer ENVI-met.")
            return
            
        ml_field = self.cb_ml_field.currentText()
        envi_field = self.cb_envi_field.currentText()
        
        if not ml_field or not envi_field:
            QMessageBox.warning(self, "Attenzione", "Seleziona i campi per entrambi i gruppi di layer.")
            return

        y_true_all = []
        y_pred_all = []
        
        # Per semplificare l'accoppiamento: assumiamo che l'utente selezioni lo stesso numero di layer 
        # ML ed ENVI-met e nello stesso ordine (es: ML_1.5 con ENVI_1.5).
        # Faremo un ciclo per accoppiarli 1 a 1 nell'ordine di selezione.
        if len(selected_ml_items) != len(selected_envi_items):
            reply = QMessageBox.question(self, "Attenzione", 
                f"Hai selezionato {len(selected_ml_items)} layer ML e {len(selected_envi_items)} layer ENVI-met.\n"
                "I layer verranno accoppiati in ordine. Sei sicuro di voler procedere?", 
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        num_pairs = min(len(selected_ml_items), len(selected_envi_items))
        
        for i in range(num_pairs):
            ml_layer_id = selected_ml_items[i].data(32)
            envi_layer_id = selected_envi_items[i].data(32)
            
            ml_layer = QgsProject.instance().mapLayer(ml_layer_id)
            envi_layer = QgsProject.instance().mapLayer(envi_layer_id)
            
            print(f"--- Elaborazione Coppia {i+1} ---")
            print(f"ML: {ml_layer.name()} | ENVI-met: {envi_layer.name()}")
            
            # CRS Check and Transform
            crs_ml = ml_layer.crs()
            crs_envi = envi_layer.crs()
            transform = None
            if crs_ml != crs_envi:
                transform = QgsCoordinateTransform(crs_ml, crs_envi, QgsProject.instance())

            # Costruzione Indice Spaziale per il layer ML corrente
            ml_idx = QgsSpatialIndex()
            ml_feats = {}
            for f in ml_layer.getFeatures():
                if transform:
                    geom = f.geometry()
                    geom.transform(transform)
                    feat_to_add = QgsFeature(f.id())
                    feat_to_add.setGeometry(geom)
                    ml_idx.addFeature(feat_to_add)
                else:
                    ml_idx.addFeature(f)
                ml_feats[f.id()] = f[ml_field]
                
            # Ricerca corrispondenze spaziali (NN)
            punti_coppia = 0
            for e_feat in envi_layer.getFeatures():
                pt = e_feat.geometry().centroid().asPoint()
                nearest_ids = ml_idx.nearestNeighbor(QgsPointXY(pt), 1)
                
                if nearest_ids:
                    ml_val = ml_feats.get(nearest_ids[0])
                    envi_val = e_feat[envi_field]
                    
                    if ml_val is not None and envi_val is not None:
                        if float(envi_val) != 0.0 or float(ml_val) != 0.0:
                            y_true_all.append(float(envi_val))
                            y_pred_all.append(float(ml_val))
                            punti_coppia += 1
            print(f"Trovati {punti_coppia} punti validi per questa coppia.")

        n = len(y_true_all)
        if n == 0:
            QMessageBox.warning(self, "Errore", "Nessun punto comune valido trovato in tutte le coppie.")
            return
            
        mean_y = sum(y_true_all) / n
        ss_tot = sum((y - mean_y)**2 for y in y_true_all)
        ss_res = sum((yt - yp)**2 for yt, yp in zip(y_true_all, y_pred_all))
        
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        rmse = math.sqrt(ss_res / n)
        mae = sum(abs(yt - yp) for yt, yp in zip(y_true_all, y_pred_all)) / n
        
        msg = (
            f"=== RISULTATI TEST GLOBALE ({num_pairs} coppie) ===\n\n"
            f"Punti validi sovrapposti totali: {n}\n\n"
            f"R² Score Globale: {r2:.4f}\n"
            f"RMSE Globale: {rmse:.4f} m/s\n"
            f"MAE Globale: {mae:.4f} m/s\n\n"
            f"Note: Ora l'R² terrà conto dell'intera varianza verticale!"
        )
        
        QMessageBox.information(self, "Risultati Correlazione", msg)
        print(msg)

# Avvia l'interfaccia
dlg = VerificaCorrelazioneDialog()
dlg.show()

