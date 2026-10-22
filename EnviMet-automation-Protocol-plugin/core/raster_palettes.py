"""
Palette colori automatiche per raster ENVI-met.

Riconosce la variabile dal nome del layer QGIS e applica una palette
scientificamente appropriata. Per variabili non riconosciute applica
una palette generica "viridis-like".
"""

import re
from qgis.core import (
    QgsRasterShader, QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer,
    QgsMessageLog, Qgis
)
from qgis.PyQt.QtGui import QColor


# ---------------------------------------------------------------------------
# Definizione palette per variabili ENVI-met note
# ---------------------------------------------------------------------------
# Ogni entry contiene:
#   "patterns": lista di regex (case-insensitive) per il matching del nome
#   "colors": lista di tuple (valore_relativo_0_1, R, G, B) per il gradiente
#   "label": nome leggibile della variabile
#   "unit": unità di misura
#
# I valori relativi (0.0 → 1.0) vengono scalati sul min/max reale del raster.
# ---------------------------------------------------------------------------

ENVIMET_PALETTES = {
    # ===================== TEMPERATURE =====================
    "air_temperature": {
        "patterns": [
            r"(?:potential\s+)?air\s+temp",
            r"temperature\s+(?:pot|air)",
            r"t\s*_?\s*air",
        ],
        "colors": [
            (0.00, 49, 54, 149),     # Blu scuro (freddo)
            (0.15, 69, 117, 180),     # Blu medio
            (0.30, 116, 173, 209),    # Azzurro
            (0.45, 171, 217, 233),    # Azzurro chiaro
            (0.50, 255, 255, 191),    # Giallo pallido (neutro)
            (0.60, 254, 224, 144),    # Giallo
            (0.70, 253, 174, 97),     # Arancione
            (0.85, 244, 109, 67),     # Rosso-arancione
            (1.00, 165, 0, 38),       # Rosso scuro (caldo)
        ],
        "label": "Temperatura dell'Aria",
        "unit": "°C",
    },

    "surface_temperature": {
        "patterns": [
            r"t\s*surface",
            r"surface\s*temp",
            r"surf.*temp",
        ],
        "colors": [
            (0.00, 49, 54, 149),
            (0.12, 69, 117, 180),
            (0.25, 116, 173, 209),
            (0.37, 171, 217, 233),
            (0.50, 255, 255, 191),
            (0.62, 254, 224, 144),
            (0.75, 253, 174, 97),
            (0.87, 244, 109, 67),
            (1.00, 165, 0, 38),
        ],
        "label": "Temperatura Superficiale",
        "unit": "°C",
    },

    "mean_radiant_temperature": {
        "patterns": [
            r"mean\s*radiant",
            r"tmrt",
            r"mrt",
        ],
        "colors": [
            (0.00, 49, 54, 149),
            (0.12, 69, 117, 180),
            (0.25, 116, 173, 209),
            (0.37, 224, 243, 248),
            (0.50, 255, 255, 191),
            (0.62, 254, 224, 144),
            (0.75, 253, 174, 97),
            (0.87, 215, 48, 39),
            (1.00, 165, 0, 38),
        ],
        "label": "Temperatura Media Radiante",
        "unit": "°C",
    },

    "soil_temperature": {
        "patterns": [
            r"soil\s*temp",
            r"temp.*soil",
        ],
        "colors": [
            (0.00, 69, 117, 180),     # Blu
            (0.25, 145, 191, 219),    # Azzurro
            (0.50, 224, 196, 146),    # Beige
            (0.75, 186, 116, 53),     # Marrone
            (1.00, 165, 0, 38),       # Rosso scuro
        ],
        "label": "Temperatura del Suolo",
        "unit": "°C",
    },

    # ===================== VENTO =====================
    "wind_speed": {
        "patterns": [
            r"wind\s*speed",
            r"velocit[àa].*vento",
        ],
        "colors": [
            (0.00, 255, 255, 255),    # Bianco (calma)
            (0.15, 199, 233, 192),    # Verde pallido
            (0.30, 127, 205, 187),    # Verde acqua
            (0.50, 65, 182, 196),     # Ciano
            (0.70, 44, 127, 184),     # Blu medio
            (0.85, 37, 82, 163),      # Blu
            (1.00, 8, 29, 88),        # Blu scuro (forte)
        ],
        "label": "Velocità del Vento",
        "unit": "m/s",
    },

    "wind_direction": {
        "patterns": [
            r"wind\s*dir",
            r"direz.*vento",
        ],
        "colors": [
            (0.00, 255, 0, 0),        # Rosso (N / 0°)
            (0.25, 255, 255, 0),       # Giallo (E / 90°)
            (0.50, 0, 255, 0),         # Verde (S / 180°)
            (0.75, 0, 255, 255),       # Ciano (W / 270°)
            (1.00, 255, 0, 0),         # Rosso (N / 360°, ciclico)
        ],
        "label": "Direzione del Vento",
        "unit": "°",
    },

    "flow_component": {
        "patterns": [
            r"flow\s*[uvw]",
        ],
        "colors": [
            (0.00, 49, 54, 149),      # Blu scuro (negativo)
            (0.25, 116, 173, 209),     # Azzurro
            (0.50, 255, 255, 255),     # Bianco (zero)
            (0.75, 253, 174, 97),      # Arancione
            (1.00, 165, 0, 38),        # Rosso (positivo)
        ],
        "label": "Componente del Flusso",
        "unit": "m/s",
    },

    # ===================== UMIDITÀ =====================
    "relative_humidity": {
        "patterns": [
            r"rel.*humid",
            r"umidi.*rel",
            r"rh\b",
        ],
        "colors": [
            (0.00, 166, 97, 26),      # Marrone (secco)
            (0.25, 223, 194, 125),     # Beige
            (0.50, 128, 205, 193),     # Verde acqua
            (0.75, 53, 151, 143),      # Teal
            (1.00, 1, 102, 148),       # Blu scuro (umido)
        ],
        "label": "Umidità Relativa",
        "unit": "%",
    },

    "specific_humidity": {
        "patterns": [
            r"spec.*humid",
            r"umidi.*spec",
        ],
        "colors": [
            (0.00, 255, 255, 255),     # Bianco
            (0.25, 199, 233, 248),     # Azzurro pallido
            (0.50, 127, 188, 220),     # Azzurro
            (0.75, 44, 127, 184),      # Blu
            (1.00, 8, 29, 88),         # Blu scuro
        ],
        "label": "Umidità Specifica",
        "unit": "g/kg",
    },

    # ===================== TURBOLENZA =====================
    "tke": {
        "patterns": [
            r"\btke\b",
            r"turbulent\s*kinetic",
        ],
        "colors": [
            (0.00, 255, 255, 255),     # Bianco
            (0.25, 218, 198, 235),     # Lavanda
            (0.50, 178, 137, 210),     # Viola chiaro
            (0.75, 128, 72, 181),      # Viola
            (1.00, 74, 20, 134),       # Viola scuro
        ],
        "label": "Energia Cinetica Turbolenta",
        "unit": "m²/s²",
    },

    "dissipation": {
        "patterns": [
            r"dissipation",
            r"dissipaz",
        ],
        "colors": [
            (0.00, 255, 255, 255),     # Bianco
            (0.25, 255, 224, 179),     # Pesca
            (0.50, 253, 174, 97),      # Arancione chiaro
            (0.75, 230, 108, 44),      # Arancione
            (1.00, 166, 54, 3),        # Arancione scuro
        ],
        "label": "Dissipazione TKE",
        "unit": "m³/s²",
    },

    "vertical_exchange": {
        "patterns": [
            r"vertical\s*exchange",
            r"exchange\s*coef",
            r"\bkm\b.*exchange",
        ],
        "colors": [
            (0.00, 255, 255, 255),     # Bianco
            (0.25, 255, 247, 188),     # Giallo pallido
            (0.50, 254, 224, 101),     # Giallo
            (0.75, 233, 185, 37),      # Oro
            (1.00, 177, 137, 0),       # Marrone dorato
        ],
        "label": "Coefficiente di Scambio Verticale",
        "unit": "m²/s",
    },

    # ===================== RADIAZIONE =====================
    "direct_sw_radiation": {
        "patterns": [
            r"direct\s*sw",
            r"direct.*shortwave",
            r"direct.*radiation",
            r"radiaz.*diretta",
        ],
        "colors": [
            (0.00, 15, 15, 15),        # Quasi nero (ombra)
            (0.20, 64, 57, 89),        # Blu-grigio scuro
            (0.40, 158, 115, 56),      # Marrone caldo
            (0.60, 240, 190, 50),      # Giallo dorato
            (0.80, 255, 235, 130),     # Giallo chiaro
            (1.00, 255, 255, 220),     # Bianco-giallo (pieno sole)
        ],
        "label": "Radiazione Solare Diretta",
        "unit": "W/m²",
    },

    "diffuse_sw_radiation": {
        "patterns": [
            r"diffuse\s*sw",
            r"diffuse.*shortwave",
            r"diffuse.*radiation",
            r"radiaz.*diffusa",
        ],
        "colors": [
            (0.00, 20, 20, 40),
            (0.25, 80, 70, 120),
            (0.50, 160, 130, 80),
            (0.75, 230, 185, 75),
            (1.00, 255, 240, 180),
        ],
        "label": "Radiazione Solare Diffusa",
        "unit": "W/m²",
    },

    "reflected_sw_radiation": {
        "patterns": [
            r"reflect.*sw",
            r"reflect.*shortwave",
            r"reflect.*radiation",
            r"radiaz.*rifles",
        ],
        "colors": [
            (0.00, 20, 20, 30),
            (0.25, 100, 85, 50),
            (0.50, 190, 160, 80),
            (0.75, 240, 210, 110),
            (1.00, 255, 245, 190),
        ],
        "label": "Radiazione Solare Riflessa",
        "unit": "W/m²",
    },

    # ===================== FLUSSI DI CALORE =====================
    "sensible_heat_flux": {
        "patterns": [
            r"sensible\s*heat",
            r"flusso.*sensib",
        ],
        "colors": [
            (0.00, 49, 54, 149),       # Blu (negativo/cooling)
            (0.25, 116, 173, 209),
            (0.50, 255, 255, 255),     # Bianco (zero)
            (0.75, 253, 174, 97),
            (1.00, 165, 0, 38),        # Rosso (positivo/heating)
        ],
        "label": "Flusso di Calore Sensibile",
        "unit": "W/m²",
    },

    "latent_heat_flux": {
        "patterns": [
            r"latent\s*heat",
            r"flusso.*latente",
        ],
        "colors": [
            (0.00, 49, 54, 149),       # Blu
            (0.25, 116, 173, 209),
            (0.50, 255, 255, 255),     # Bianco (zero)
            (0.75, 144, 213, 142),     # Verde chiaro
            (1.00, 0, 104, 55),        # Verde scuro
        ],
        "label": "Flusso di Calore Latente",
        "unit": "W/m²",
    },

    # ===================== COMFORT TERMICO =====================
    "pet": {
        "patterns": [
            r"\bpet\b",
            r"physiological\s*equiv",
        ],
        "colors": [
            (0.00, 49, 54, 149),       # Blu scuro (molto freddo)
            (0.15, 69, 117, 180),      # Blu
            (0.30, 116, 173, 209),     # Azzurro
            (0.40, 102, 189, 99),      # Verde
            (0.50, 190, 229, 113),     # Verde-giallo (comfort)
            (0.60, 254, 224, 76),      # Giallo
            (0.75, 253, 174, 97),      # Arancione
            (0.87, 244, 109, 67),      # Rosso-arancione
            (1.00, 165, 0, 38),        # Rosso scuro (caldo estremo)
        ],
        "label": "PET (Temperatura Equiv. Fisiologica)",
        "unit": "°C",
    },

    "utci": {
        "patterns": [
            r"\butci\b",
            r"universal\s*thermal",
        ],
        "colors": [
            (0.00, 0, 51, 153),        # Blu molto scuro (stress freddo estremo)
            (0.10, 49, 54, 149),
            (0.20, 69, 117, 180),      # Blu
            (0.30, 116, 173, 209),     # Azzurro
            (0.40, 102, 189, 99),      # Verde (nessuno stress)
            (0.50, 190, 229, 113),     # Verde-giallo
            (0.60, 254, 224, 76),      # Giallo (stress moderato)
            (0.70, 253, 174, 97),      # Arancione
            (0.80, 244, 109, 67),      # Rosso-arancione (stress forte)
            (0.90, 215, 48, 39),       # Rosso
            (1.00, 128, 0, 0),         # Rosso scuro (stress estremo)
        ],
        "label": "UTCI (Indice Termico Climatico Universale)",
        "unit": "°C",
    },

    "pmv": {
        "patterns": [
            r"\bpmv\b",
            r"predicted\s*mean\s*vote",
        ],
        "colors": [
            (0.00, 49, 54, 149),       # Blu scuro (-4, molto freddo)
            (0.20, 69, 117, 180),
            (0.35, 116, 173, 209),     # Azzurro
            (0.50, 102, 189, 99),      # Verde (0, comfort)
            (0.65, 254, 224, 76),      # Giallo
            (0.80, 244, 109, 67),      # Arancione
            (1.00, 165, 0, 38),        # Rosso (+4, molto caldo)
        ],
        "label": "PMV (Voto Medio Previsto)",
        "unit": "-",
    },

    "set_temperature": {
        "patterns": [
            r"\bset\b.*temp",
            r"standard\s*effective",
        ],
        "colors": [
            (0.00, 49, 54, 149),
            (0.20, 69, 117, 180),
            (0.35, 116, 173, 209),
            (0.50, 190, 229, 113),
            (0.65, 254, 224, 76),
            (0.80, 244, 109, 67),
            (1.00, 165, 0, 38),
        ],
        "label": "SET (Temperatura Effettiva Standard)",
        "unit": "°C",
    },

    # ===================== SUOLO =====================
    "soil_water_content": {
        "patterns": [
            r"soil\s*water",
            r"water\s*content.*soil",
            r"contenuto.*acqua.*suolo",
        ],
        "colors": [
            (0.00, 166, 97, 26),       # Marrone (secco)
            (0.25, 223, 194, 125),
            (0.50, 186, 228, 188),     # Verde acqua
            (0.75, 67, 162, 202),      # Blu
            (1.00, 8, 64, 129),        # Blu scuro (saturo)
        ],
        "label": "Contenuto Idrico del Suolo",
        "unit": "m³/m³",
    },
}


# ---------------------------------------------------------------------------
# Palette generica per variabili non riconosciute (stile "viridis")
# ---------------------------------------------------------------------------
DEFAULT_PALETTE_COLORS = [
    (0.00, 68, 1, 84),        # Viola scuro
    (0.10, 72, 35, 116),
    (0.20, 64, 67, 135),
    (0.30, 52, 94, 141),
    (0.40, 33, 144, 140),     # Teal
    (0.50, 43, 176, 122),     # Verde acqua
    (0.60, 93, 201, 98),      # Verde
    (0.70, 156, 217, 59),     # Lime
    (0.80, 210, 226, 27),     # Giallo-verde
    (0.90, 253, 231, 37),     # Giallo
    (1.00, 253, 231, 37),     # Giallo
]


def _detect_variable(layer_name):
    """
    Analizza il nome di un layer QGIS per identificare la variabile ENVI-met.
    
    I nomi tipici ENVI-met seguono il pattern:
        "Variable Name_DD.MM._HH.MM.SS_height_SeriesX"
    Es: "Wind Speed_29.03._06.00.00_0.0m-3.0m_SeriesA"
    
    Returns:
        str or None: La chiave del dizionario ENVIMET_PALETTES, o None se non riconosciuta.
    """
    # Estrai la parte del nome prima della data (separatore tipico: _DD.MM.)
    # Questo è il nome "puro" della variabile
    var_part = layer_name
    date_match = re.search(r'_\d{2}\.\d{2}\.', layer_name)
    if date_match:
        var_part = layer_name[:date_match.start()]
    
    # Prova anche il separatore ISO date
    iso_match = re.search(r'_\d{4}-\d{2}-\d{2}', layer_name)
    if iso_match:
        var_part = layer_name[:iso_match.start()]
    
    # Rimuovi prefisso sub-area se presente (es. "SubArea1_Wind Speed")
    # Il formato tipico dopo l'allineamento è: "SubAreaName_VariableName... (Allineato)"
    # Cerchiamo pattern noti nella parte rimanente
    
    var_part_lower = var_part.lower().strip()
    
    for key, palette_def in ENVIMET_PALETTES.items():
        for pattern in palette_def["patterns"]:
            if re.search(pattern, var_part_lower):
                return key
            # Cerca anche nell'intero nome del layer (in caso il prefisso sub-area
            # sposti la variabile più avanti nel nome)
            if re.search(pattern, layer_name.lower()):
                return key
    
    return None


def _get_raster_min_max(layer):
    """
    Calcola i valori min e max reali dal raster (banda 1) usando GDAL.
    
    Usa GDAL direttamente perché QgsRasterBandStats può restituire valori
    errati (0-255) in alcune versioni di QGIS quando le statistiche non sono
    ancora state calcolate.
    
    Returns:
        tuple: (min_val, max_val) o (0, 1) in caso di errore
    """
    try:
        from osgeo import gdal
        ds = gdal.Open(layer.source())
        if not ds:
            raise RuntimeError(f"GDAL non riesce ad aprire {layer.source()}")
        
        band = ds.GetRasterBand(1)
        
        # ComputeRasterMinMax(False) = calcolo esatto (non approssimato)
        # Ignora automaticamente i pixel NoData
        real_min, real_max = band.ComputeRasterMinMax(False)
        
        ds = None  # Chiudi il dataset
        
        QgsMessageLog.logMessage(
            f"Statistiche GDAL calcolate: min={real_min:.6f}, max={real_max:.6f}",
            "EnviProtocol", Qgis.Info
        )
        
        if real_min == real_max:
            return real_min - 1, real_max + 1
        
        return real_min, real_max
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Errore calcolo statistiche GDAL: {e}",
            "EnviProtocol", Qgis.Warning
        )
        return 0, 1


def apply_envimet_palette(layer, original_layer_name="", override_palette_name=""):
    """
    Applica una palette colori al raster ENVI-met basandosi sul nome della variabile.
    
    Se la variabile è riconosciuta, usa la palette specifica.
    Altrimenti, applica la palette generica "viridis-like".
    In alternativa, se viene specificato override_palette_name, applica quella standard di QGIS.
    
    Args:
        layer: QgsRasterLayer da stilizzare
        original_layer_name: Il nome originale del layer (pre-allineamento)
                           usato per identificare la variabile
        override_palette_name: Nome di una color ramp standard di QGIS (opzionale)
    """
    if not layer or not layer.isValid():
        return
    
    # Usa il nome originale per il matching, o il nome attuale del layer
    search_name = original_layer_name if original_layer_name else layer.name()
    
    # Identifica la variabile
    var_key = _detect_variable(search_name)
    
    if var_key and var_key in ENVIMET_PALETTES:
        palette_def = ENVIMET_PALETTES[var_key]
        colors = palette_def["colors"]
        label = palette_def["label"]
        unit = palette_def["unit"]
        QgsMessageLog.logMessage(
            f"Palette riconosciuta: '{label}' ({unit}) per layer '{search_name}'",
            "EnviProtocol", Qgis.Info
        )
    else:
        colors = DEFAULT_PALETTE_COLORS
        label = "Variabile"
        unit = ""
        QgsMessageLog.logMessage(
            f"Variabile non riconosciuta per '{search_name}', applico palette generica viridis",
            "EnviProtocol", Qgis.Info
        )
    
    # Ottieni min/max reali dal raster tramite GDAL
    min_val, max_val = _get_raster_min_max(layer)
    val_range = max_val - min_val
    
    QgsMessageLog.logMessage(
        f"Applicazione palette con range reale: {min_val:.4f} - {max_val:.4f}",
        "EnviProtocol", Qgis.Info
    )
    
    # Costruisci la lista di ColorRampItem con valori reali
    ramp_items = []
    
    used_override = False
    if override_palette_name:
        from qgis.core import QgsStyle
        color_ramp_obj = QgsStyle.defaultStyle().colorRamp(override_palette_name)
        if color_ramp_obj:
            used_override = True
            QgsMessageLog.logMessage(
                f"Applico palette custom: '{override_palette_name}'",
                "EnviProtocol", Qgis.Info
            )
            for i in range(11):
                t = i / 10.0
                c = color_ramp_obj.color(t)
                value = min_val + t * val_range
                item_label = f"{value:.2f} {unit}" if unit else f"{value:.4f}"
                ramp_items.append(
                    QgsColorRampShader.ColorRampItem(value, c, item_label)
                )

    if not used_override:
        for rel_pos, r, g, b in colors:
            value = min_val + rel_pos * val_range
            color = QColor(r, g, b)
            # Etichetta: mostra il valore con unità
            if unit:
                item_label = f"{value:.2f} {unit}"
            else:
                item_label = f"{value:.4f}"
            ramp_items.append(
                QgsColorRampShader.ColorRampItem(value, color, item_label)
            )
    
    # Crea lo shader con interpolazione lineare
    color_ramp = QgsColorRampShader()
    color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
    color_ramp.setColorRampItemList(ramp_items)
    # Forza i limiti min/max sullo shader
    color_ramp.setMinimumValue(min_val)
    color_ramp.setMaximumValue(max_val)
    color_ramp.setClassificationMode(QgsColorRampShader.Continuous)
    
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(color_ramp)
    
    # Applica il renderer pseudo-colore a banda singola
    renderer = QgsSingleBandPseudoColorRenderer(
        layer.dataProvider(), 1, shader
    )
    # Forza min/max reali sul renderer (controlla la legenda)
    renderer.setClassificationMin(min_val)
    renderer.setClassificationMax(max_val)
    
    layer.setRenderer(renderer)
    layer.emitStyleChanged()
    layer.triggerRepaint()

