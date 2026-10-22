import re
import csv
import numpy as np
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel, QScrollArea, 
                                 QWidget, QFrame, QHBoxLayout, QSizePolicy, 
                                 QPushButton, QFileDialog, QMessageBox)
from qgis.PyQt.QtCore import Qt, QMarginsF
from qgis.PyQt.QtGui import QPainter, QPdfWriter, QPageLayout, QPageSize
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class StatsVisualizer(QDialog):
    def __init__(self, stats_data, parent=None):
        super(StatsVisualizer, self).__init__(parent)
        self.setWindowTitle("Analisi Termo-Fluidodinamica: Varianza e Residui")
        self.resize(1100, 850)
        self.stats_data = stats_data
        self.report_pages = [] 
        self.setup_ui()
        
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        # UI Control per l'esportazione PDF
        export_btn = QPushButton("Esporta Report PDF Multipagina (A4 Landscape)")
        export_btn.setStyleSheet("""
            QPushButton {
                padding: 10px; 
                font-weight: bold; 
                background-color: #2c3e50; 
                color: white; 
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #34495e;
            }
        """)
        export_btn.clicked.connect(self.export_pdf)
        main_layout.addWidget(export_btn)

        # NUOVO BOTTONE per esportazione CSV (Machine Learning)
        export_csv_btn = QPushButton("Esporta Dataset CSV (Machine Learning)")
        export_csv_btn.setStyleSheet("""
            QPushButton {
                padding: 10px; 
                font-weight: bold; 
                background-color: #27ae60; 
                color: white; 
                border-radius: 4px;
                font-size: 12px;
                margin-top: 5px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        export_csv_btn.clicked.connect(self.export_csv)
        main_layout.addWidget(export_csv_btn)
        
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        
        container = QWidget()
        container.setStyleSheet("background-color: #eaeded;")
        container_layout = QVBoxLayout(container)
        
        if not self.stats_data:
            container_layout.addWidget(QLabel("Errore: Nessuna congruenza topologica o di nomenclatura rilevata."))
        
        for data in self.stats_data:
            page_widget = QWidget()
            page_widget.setStyleSheet("background-color: white; border-radius: 6px;")
            page_widget.setFixedSize(1020, 460)  
            page_layout = QVBoxLayout(page_widget)
            
            header = QLabel(f"CONFRONTO VERTICALE: {data['aeris_layer']} vs {data['griglia_layer']}")
            header.setStyleSheet("font-size: 13px; font-weight: bold; color: #2c3e50; background-color: #ecf0f1; padding: 8px; border-radius: 4px;")
            page_layout.addWidget(header)
            
            h_layout = QHBoxLayout()
            
            stats_frame = QFrame()
            stats_frame.setFixedWidth(280)
            stats_layout = QVBoxLayout(stats_frame)
            
            metrics = [
                (f"Pearson r: {data['pearson']:.4f}", "Allineamento di fase e collinearità spaziale temporale."),
                (f"R²: {data['r_squared']:.4f}", "Percentuale di varianza lineare spiegata tra i modelli."),
                (f"MBE: {data['mbe']:.4f} m/s", "Spostamento sistematico medio (Bias volumetrico)."),
                (f"RMSE: {data['rmse']:.4f} m/s", "Dispersione quadratica media (sensibilità agli outlier locali).")
            ]
            
            for val, desc in metrics:
                lbl_val = QLabel(f"<b>{val}</b>")
                lbl_val.setStyleSheet("font-size: 12px; color: #c0392b;")
                lbl_desc = QLabel(f"<i>{desc}</i>")
                lbl_desc.setWordWrap(True)
                lbl_desc.setStyleSheet("font-size: 11px; color: #7f8c8d; margin-bottom: 8px;")
                stats_layout.addWidget(lbl_val)
                stats_layout.addWidget(lbl_desc)
                
            stats_layout.addStretch()
            h_layout.addWidget(stats_frame)
            
            fig = Figure(figsize=(7, 3.5), dpi=110)
            canvas = FigureCanvas(fig)
            canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            
            ax1 = fig.add_subplot(121)
            ax2 = fig.add_subplot(122)
            
            x = data['arr_aeris']
            y = data['arr_griglia']
            
            ax1.scatter(y, x, alpha=0.3, s=10, c='#2980b9', edgecolors='none')
            min_val = min(np.min(x), np.min(y))
            max_val = max(np.max(x), np.max(y))
            ax1.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=1.5, label='1:1 Ideal')
            ax1.set_title("Scatter: ENVI-met vs Aeris", fontsize=9, fontweight='bold')
            ax1.set_xlabel("ENVI-met (Median_median) [m/s]", fontsize=8)
            ax1.set_ylabel("Aeris (u_z) [m/s]", fontsize=8)
            ax1.grid(True, linestyle=':', alpha=0.6)
            ax1.legend(loc='upper left', fontsize=7)
            
            residuals = x - y
            ax2.hist(residuals, bins=50, color='#e74c3c', alpha=0.7, edgecolor='black', linewidth=0.5)
            ax2.axvline(0, color='black', linestyle='dashed', linewidth=1)
            ax2.axvline(np.mean(residuals), color='blue', linestyle='solid', linewidth=1.5, label=f'MBE ({data["mbe"]:.2f})')
            ax2.set_title("Distribuzione dei Residui", fontsize=9, fontweight='bold')
            ax2.set_xlabel("Errore (Δ m/s)", fontsize=8)
            ax2.set_ylabel("Frequenza (Celle)", fontsize=8)
            ax2.grid(True, linestyle=':', alpha=0.6)
            ax2.legend(loc='upper right', fontsize=7)
            
            fig.tight_layout()
            h_layout.addWidget(canvas)
            
            page_layout.addLayout(h_layout)
            container_layout.addWidget(page_widget)
            
            self.report_pages.append(page_widget)
            
        container_layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Esporta Report PDF", "report_comparazione_verticale.pdf", "PDF Files (*.pdf)")
        if not path: 
            return

        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
        writer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
        
        painter = QPainter(writer)
        
        for i, page_widget in enumerate(self.report_pages):
            if i > 0:
                writer.newPage()
            
            target_rect = painter.viewport()
            widget_size = page_widget.size()
            
            scale_x = target_rect.width() / widget_size.width()
            scale_y = target_rect.height() / widget_size.height()
            scale_factor = min(scale_x, scale_y)
            
            painter.save()
            painter.scale(scale_factor, scale_factor)
            page_widget.render(painter)  
            painter.restore()
            
        painter.end()

    def export_csv(self):
        """Genera e salva un CSV con i dati allineati per il Machine Learning."""
        path, _ = QFileDialog.getSaveFileName(self, "Esporta Dataset CSV", "dataset_aeris_ml.csv", "CSV Files (*.csv)")
        if not path:
            return
            
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Intestazione del CSV
                writer.writerow(['z_target', 'h_ost', 'lambda_p', 'u_aeris', 'u_envimet'])
                
                # Itera per ogni livello di quota analizzato
                for data in self.stats_data:
                    z = data['z_val']
                    # Salva riga per riga (cella per cella)
                    for i in range(len(data['arr_aeris'])):
                        u_a = data['arr_aeris'][i]
                        u_e = data['arr_griglia'][i]
                        
                        # Estrai i parametri fisici se esistono, altrimenti 0
                        h = data['arr_host'][i] if 'arr_host' in data and i < len(data['arr_host']) else 0.0
                        lp = data['arr_lambda'][i] if 'arr_lambda' in data and i < len(data['arr_lambda']) else 0.0
                        
                        writer.writerow([z, h, lp, u_a, u_e])
            
            QMessageBox.information(self, "Export Completato", "Dataset per Machine Learning esportato con successo!\nPuoi caricare questo CSV per l'analisi.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante l'esportazione:\n{str(e)}")

def extract_array_safe(layer, field_name, default_val=0.0):
    """Estrae l'array. Se la colonna non esiste, restituisce un array di zeri."""
    idx = layer.fields().indexOf(field_name)
    features = sorted(list(layer.getFeatures()), key=lambda f: f.id())
    if idx == -1:
        return np.array([default_val] * len(features), dtype=float)
    
    return np.array([(f[idx] if f[idx] is not None else default_val) for f in features], dtype=float)

def extract_array(layer, field_name):
    """Estrazione stretta (restituisce None se manca il campo). Usato per i campi essenziali."""
    idx = layer.fields().indexOf(field_name)
    if idx == -1: return None
    features = sorted(list(layer.getFeatures()), key=lambda f: f.id())
    return np.array([f[idx] for f in features if f[idx] is not None], dtype=float)

def process_layers():
    project = QgsProject.instance()
    layers = project.mapLayers().values()
    
    aeris_layers = {}
    griglia_layers = []
    
    for layer in layers:
        name = layer.name()
        if name.startswith("aeris_vettoriale_vento_"):
            try:
                z_val = float(name.split("_")[-1])
                aeris_layers[z_val] = layer
            except ValueError: pass
        elif name.startswith("Griglia_Statistiche_"):
            match = re.search(r'([0-9.]+)[mM]?\-([0-9.]+)[mM]?', name)
            if match:
                griglia_layers.append((float(match.group(1)), float(match.group(2)), layer))

    results = []
    for z_min, z_max, g_layer in griglia_layers:
        z_mid = (z_min + z_max) / 2.0
        matching_z = [z for z in aeris_layers.keys() if abs(z - z_mid) < 0.01]
        
        if matching_z:
            z_exact = matching_z[0]
            a_layer = aeris_layers[z_exact]
            
            arr_aeris = extract_array(a_layer, "u_z")
            arr_griglia = extract_array(g_layer, "Median_median")
            
            if arr_aeris is None or arr_griglia is None: continue
                
            min_len = min(len(arr_aeris), len(arr_griglia))
            x = arr_aeris[:min_len]
            y = arr_griglia[:min_len]
            
            # Estrazione parametri fisici aggiuntivi per il Machine Learning
            arr_host = extract_array_safe(a_layer, "h_ost_val", default_val=0.0)[:min_len]
            arr_lambda = extract_array_safe(a_layer, "lambda_p", default_val=0.0)[:min_len]
            
            mbe = np.mean(y - x)
            rmse = np.sqrt(np.mean((y - x)**2))
            pearson_r = 0.0 if np.std(x) == 0 or np.std(y) == 0 else np.corrcoef(x, y)[0, 1]
            
            results.append({
                'aeris_layer': a_layer.name(),
                'griglia_layer': g_layer.name(),
                'z_val': z_exact,  
                'mbe': mbe,
                'rmse': rmse,
                'pearson': pearson_r,
                'r_squared': pearson_r**2,
                'arr_aeris': x,
                'arr_griglia': y,
                'arr_host': arr_host,
                'arr_lambda': arr_lambda
            })
            
    results.sort(key=lambda x: x['z_val'])
    return results

stats = process_layers()
dialog = StatsVisualizer(stats)
dialog.exec()
