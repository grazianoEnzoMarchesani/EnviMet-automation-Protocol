# -*- coding: utf-8 -*-
"""
Centralized Constants Module for EnviProtocol Plugin

Contains all hardcoded layer names, field names, file names,
and folder mappings used by the data acquisition engine.
"""


class LayerNames:
    """Display names for map layers loaded into QGIS."""
    
    # Unified data layers
    DTM = "DTM Tinitaly (10m)"
    BUILDINGS = "Edifici TUM LoD1"
    CANOPY = "Altezza Alberi ETH (10m)"
    LANDUSE = "Land Use ESA (10m)"
    ROADS = "Reti Stradali OSM"
    IMPERVIOUSNESS = "Impermeabilità Copernicus (10m)"
    TCD = "Tree Cover Density Copernicus (10m)"


class FileNames:
    """File names for unified/processed data outputs."""
    
    # Unified raster outputs
    DTM = "dtm_10m.tif"
    CANOPY = "canopy_height_10m.tif"
    LANDUSE = "landuse_10m.tif"
    IMPERVIOUSNESS = "imperviousness_10m.tif"
    TCD = "tcd_10m.tif"
    
    # ENVI-met Export outputs
    EM_SUB_AREA = "sub_area.gpkg"
    EM_SURFACES = "surfaces.gpkg"
    EM_VEGETATION = "vegetation.gpkg"
    EM_SIMPLE_PLANTS = "simple_plants.gpkg"
    EM_BUILDINGS = "buildings_prepared.gpkg"
    
    # Unified vector outputs
    BUILDINGS = "buildings_lod1.gpkg"
    ROADS = "roads.gpkg"


class FieldNames:
    """Field names used in unified layer attributes."""
    pass


class FolderNames:
    """Subfolder names for downloaded/processed data."""
    
    TINITALY = "tinitaly_tiles"
    TUM = "tum_lod1"
    ETH = "eth_canopy"
    ESA = "esa_worldcover"
    OSM = "osm_roads"
    HRL = "copernicus_hrl"
    SNAPSHOTS = "snapshots"
    ENVIMET = "envimet_export"


class ProjectHeaders:
    """Standard headers for ENVI-met layers."""
    ENVIMET = "Integrazione ENVI-met"


# Mapping from ESA WorldCover to real ENVI-met Soil Profile IDs
# These are used to tag vector polygons during the "Prepare for ENVI-met" task.
ESA_ENVIMET_MAPPING = {
    10: "0200SL",   # Trees -> Default Unsealed Soil (Sandy Loam)
    20: "0200SL",   # Shrubland -> Default Unsealed Soil (Sandy Loam)
    30: "0200SL",   # Grassland -> Default Unsealed Soil (Sandy Loam)
    40: "0200LO",   # Cropland -> Loam
    50: "0200PG",   # Built-up -> Concrete Pavement Gray (Typical for urban yards/pavements)
    60: "0200SD",   # Bare / sparse vegetation -> Sandy Soil
    70: "0200WW",   # Snow and Ice -> Water (thermal proxy)
    80: "0200WW",   # Permanent water bodies -> Deep Water
    90: "0200LO",   # Herbaceous wetland -> Loam (Wetland proxy)
    95: "0200WW",   # Mangroves -> Deep Water
    100: "0200LO"   # Moss and lichen -> Loam
}


# Mapping from ESA WorldCover to ENVI-met Simple Plant IDs
# 20: Shrubland, 30: Grassland, 40: Cropland, 90: Herbaceous wetland, 100: Moss and lichen
ESA_SIMPLE_PLANT_MAPPING = {
    20: "0200H1",   # Shrubland -> Hedge dense, 1m (Proxy)
    30: "0200XX",   # Grassland -> Grass 25 cm aver. dense
    40: "0200SO",   # Cropland -> Soja 63cm
    90: "0200XY",   # Herbaceous wetland -> Grass 50 cm aver. dense
    100: "0200XX"   # Moss and lichen -> Grass 25 cm
}


# Mapping from OSM Highway Type to realistic width (meters)
# Total width (e.g. 10m means 5m buffer on each side)
ROAD_WIDTH_MAPPING = {
    "motorway": 12.0,
    "trunk": 10.0,
    "primary": 9.0,
    "secondary": 7.5,
    "tertiary": 6.0,
    "residential": 5.0,
    "living_street": 4.0,
    "service": 3.5,
    "pedestrian": 4.0,
    "path": 1.5,
    "footway": 1.5,
    "cycleway": 2.0,
    "default": 4.0
}

# Mapping from OSM Highway Type to ENVI-met Soil ID
ROAD_MATERIAL_MAPPING = {
    "motorway": "0200ST",
    "trunk": "0200ST",
    "primary": "0200ST",
    "secondary": "0200ST",
    "tertiary": "0200ST",
    "residential": "0200ST",
    "living_street": "0200ST",
    "service": "0200ST",
    "pedestrian": "0200PG", # Gray Pavement for pedestrians
    "path": "0200SL",       # Unsealed for paths
    "footway": "0200PG",
    "cycleway": "0200ST",
    "default": "0200ST"
}

# Building Defaults
BUILDING_WALL_MATERIAL_DEFAULT = "000000"  # Default Wall - moderate insulation
BUILDING_ROOF_MATERIAL_DEFAULT = "000000"  # Default Wall - moderate insulation
BUILDING_WALL_GREENING_DEFAULT = ""        # No greening
BUILDING_ROOF_GREENING_DEFAULT = ""        # No greening
