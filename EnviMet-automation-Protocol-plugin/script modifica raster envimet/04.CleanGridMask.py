import os
import processing
from qgis.core import QgsProject, QgsVectorLayer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, 
    QListWidget, QAbstractItemView, QPushButton, QMessageBox
)

class GridFilterCleanDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Filtro Griglia Vergine (QGIS 4)")
        self.resize(400, 350)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Seleziona il layer della Griglia Vettoriale:"))
        self.combo_grid = QComboBox(self)
        layout.addWidget(self.combo_grid)
        
        layout.addWidget(QLabel("Seleziona i layer di Limite:"))
        self.list_limits = QListWidget(self)
        self.list_limits.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        layout.addWidget(self.list_limits)
        
        self.populate_layers()
        
        self.btn_run = QPushButton("Esegui ed Esporta Griglia Vergine", self)
        self.btn_run.clicked.connect(self.process_extraction)
        layout.addWidget(self.btn_run)
        
    def populate_layers(self):
        layers = QgsProject.instance().mapLayers().values()
        vlayers = [l for l in layers if isinstance(l, QgsVectorLayer)]
        for layer in vlayers:
            self.combo_grid.addItem(layer.name(), layer)
            self.list_limits.addItem(layer.name())
            item = self.list_limits.item(self.list_limits.count() - 1)
            item.setData(0x0100, layer)

    def process_extraction(self):
        project = QgsProject.instance()
        project_dir = project.absolutePath()
        
        if not project_dir:
            QMessageBox.critical(
                self, 
                "Progetto non salvato", 
                "Il progetto corrente non è salvato su disco. Salva il progetto prima di procedere."
            )
            return

        grid_layer = self.combo_grid.currentData()
        selected_items = self.list_limits.selectedItems()
        limit_layers = [item.data(0x0100) for item in selected_items]
        
        if not grid_layer or not limit_layers:
            QMessageBox.warning(self, "Errore", "Selezionare la griglia e almeno un limite.")
            return
            
        self.btn_run.setEnabled(False)
        self.btn_run.setText("Scrittura griglia vergine...")
        
        try:
            output_filename = f"Griglia_Vergine_{grid_layer.name()}.gpkg"
            output_path = os.path.normpath(os.path.join(project_dir, output_filename))
            
            # 1. Unione dei layer limite in memoria
            if len(limit_layers) > 1:
                merge_params = {
                    'LAYERS': limit_layers,
                    'CRS': grid_layer.crs().authid(),
                    'OUTPUT': 'memory:merged_limits'
                }
                merged_result = processing.run("native:mergevectorlayers", merge_params)
                target_limits = merged_result['OUTPUT']
            else:
                target_limits = limit_layers[0]
                
            # 2. Estrazione per posizione in un layer temporaneo in memoria
            extract_params = {
                'INPUT': grid_layer,
                'PREDICATE': [6], # within
                'INTERSECT': target_limits,
                'OUTPUT': 'memory:temp_filtered_grid'
            }
            extraction_result = processing.run("native:extractbylocation", extract_params)
            temp_layer = extraction_result['OUTPUT']
            
            # 3. Rimozione radicale di tutti i campi attributo dal layer temporaneo
            if temp_layer.fields().count() > 0:
                # Recupera gli indici di tutti i campi presenti
                field_ids = list(range(temp_layer.fields().count()))
                temp_layer.startEditing()
                temp_layer.dataProvider().deleteAttributes(field_ids)
                temp_layer.commitChanges()
                temp_layer.updateFields() # Aggiorna la struttura interna dei metadati

            # 4. Salvataggio del layer privo di attributi nel file GeoPackage finale
            save_params = {
                'INPUT': temp_layer,
                'OUTPUT': output_path
            }
            processing.run("native:savefeatures", save_params)
            
            # Caricamento del file risultante in QGIS
            final_layer = QgsVectorLayer(output_path, f"Griglia_Vergine_{grid_layer.name()}", "ogr")
            if final_layer.isValid():
                project.addMapLayer(final_layer)
                QMessageBox.information(
                    self, 
                    "Successo", 
                    f"Griglia vergine (senza attributi) creata e salvata in:\n{output_path}"
                )
                self.accept()
            else:
                raise Exception("Errore nell'inizializzazione del layer finale OGR.")
            
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante l'elaborazione:\n{str(e)}")
            self.btn_run.setEnabled(True)
            self.btn_run.setText("Esegui ed Esporta Griglia Vergine")

dialog = GridFilterCleanDialog()
dialog.show()