# -*- coding: utf-8 -*-

import os
import time
import json
import requests
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsRectangle, Qgis
)


class OSMDownloader:
    """
    Robust multi-server OSM Road Downloader.
    Queries multiple Overpass API mirrors and the official OpenStreetMap API v0.6
    in fallback sequence until valid road geometry data is actually received.
    """

    # Valid highway types for urban microclimate modeling
    VALID_HIGHWAYS = {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "residential", "service", "unclassified", "living_street",
        "pedestrian", "footway", "cycleway", "path", "track", "steps",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
        "tertiary_link", "living_street_link", "road"
    }

    HIGHWAY_REGEX = (
        "^(motorway|trunk|primary|secondary|tertiary|residential|service|"
        "unclassified|living_street|pedestrian|footway|cycleway|path|"
        "track|steps|.*_link|road)$"
    )

    def __init__(self, data_manager):
        self.dm = data_manager
        self.overpass_url = "https://overpass.openstreetmap.fr/api/interpreter"
        # Ordered list of (name, provider_type, endpoint_url)
        self.sources = [
            ("Overpass France (openstreetmap.fr)", "overpass", "https://overpass.openstreetmap.fr/api/interpreter"),
            ("OSM API v0.6 Ufficiale (openstreetmap.org)", "osm_api_v06", "https://api.openstreetmap.org/api/0.6/map.json"),
            ("Overpass Main (overpass-api.de)", "overpass", "https://overpass-api.de/api/interpreter"),
            ("Overpass Private.coffee (kumi mirror)", "overpass", "https://overpass.private.coffee/api/interpreter"),
            ("Overpass LZ4 (lz4.overpass-api.de)", "overpass", "https://lz4.overpass-api.de/api/interpreter"),
            ("Overpass Z (z.overpass-api.de)", "overpass", "https://z.overpass-api.de/api/interpreter"),
            ("Overpass VK/Mail.ru (maps.mail.ru)", "overpass", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"),
            ("Overpass Kumi (overpass.kumi.systems)", "overpass", "https://overpass.kumi.systems/api/interpreter"),
        ]

    def _is_existing_file_valid(self, filepath, bbox):
        """
        Checks if roads.geojson exists, contains at least 1 road feature,
        and overlaps with the current AOI bounding box (south, west, north, east).
        """
        if not os.path.exists(filepath):
            return False
        try:
            if os.path.getsize(filepath) <= 100:
                return False
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            features = data.get("features", [])
            if not features:
                return False

            south, west, north, east = bbox
            # Add a small tolerance (~500m in degrees) for boundary roads
            tol = 0.005
            for feat in features:
                coords = feat.get("geometry", {}).get("coordinates", [])
                for pt in coords:
                    if len(pt) >= 2:
                        lon, lat = pt[0], pt[1]
                        if (west - tol <= lon <= east + tol) and (south - tol <= lat <= north + tol):
                            return True
            return False
        except Exception:
            return False

    def fetch_roads(self, extent, crs_auth_id, log_callback=None, cancel_check=None):
        """
        Fetches road segments from OSM by cycling through multiple Overpass servers
        and the official OSM API v0.6 until actual road data is downloaded.
        """
        def log(msg):
            if log_callback:
                log_callback(msg)

        output_dir = self.dm.get_download_dir("osm_roads")
        if not output_dir:
            return False, "Project not saved"

        output_path = os.path.join(output_dir, "roads.geojson")

        # 1. Transform extent to EPSG:4326
        log("Parametrizzazione query OSM (AOI -> EPSG:4326)...")
        source_crs = QgsCoordinateReferenceSystem(crs_auth_id)
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(
            source_crs, target_crs, QgsProject.instance().transformContext()
        )
        w84_extent = transform.transformBoundingBox(extent)

        bbox = (
            round(w84_extent.yMinimum(), 6),
            round(w84_extent.xMinimum(), 6),
            round(w84_extent.yMaximum(), 6),
            round(w84_extent.xMaximum(), 6),
        )  # (south, west, north, east)

        # Validate existing file against current AOI
        if self._is_existing_file_valid(output_path, bbox):
            log("Dati OSM già presenti e validi per l'AOI corrente, salto download.")
            return True, f"Dati OSM già presenti: {output_path}"

        if os.path.exists(output_path):
            log("Rilevato file roads.geojson vuoto, incompleto o relativo a un'altra AOI. Procedo con il nuovo download...")

        log(f"Ricerca strade OSM su bbox (S,W,N,E): {bbox}")

        headers = {
            "User-Agent": "EnviProtocolPlugin/1.1 (QGIS Plugin; contact: graziano)",
            "Accept": "application/json",
        }

        empty_fallback_geojson = None
        last_error = "Nessun server disponibile"

        # 2. Multi-server acquisition loop (Pass 1: fast timeouts, Pass 2: extended timeouts if all failed)
        for attempt_pass, (conn_timeout, read_timeout) in enumerate([(8, 25), (12, 50)], start=1):
            if attempt_pass > 1:
                log("Tutti i server hanno fallito al primo giro. Secondo tentativo con timeout esteso...")

            for srv_idx, (srv_name, srv_type, srv_url) in enumerate(self.sources, start=1):
                if cancel_check and cancel_check():
                    return False, "Canceled"

                log(f"[{srv_idx}/{len(self.sources)}] Tentativo download da {srv_name}...")

                try:
                    if srv_type == "overpass":
                        osm_data = self._query_overpass_server(
                            srv_url, bbox, headers,
                            timeout=(conn_timeout, read_timeout),
                            use_out_geom=(attempt_pass == 1),
                            log=log
                        )
                    elif srv_type == "osm_api_v06":
                        osm_data = self._query_osm_api_v06(
                            srv_url, bbox, headers,
                            timeout=(conn_timeout, read_timeout),
                            log=log,
                            cancel_check=cancel_check
                        )
                    else:
                        continue

                    if not osm_data:
                        continue

                    geojson = self._osm_to_geojson(osm_data)
                    num_features = len(geojson.get("features", []))

                    if num_features > 0:
                        log(f"✓ Ricevuti {num_features} segmenti stradali validi da {srv_name}.")
                        self._save_geojson_atomic(geojson, output_path)
                        log(f"Salvataggio completato: {output_path}")
                        return True, output_path
                    else:
                        empty_fallback_geojson = geojson
                        log(f"⚠ {srv_name} ha risposto ma con 0 strade nell'area. Provo un altro server per sicurezza...")

                except Exception as e:
                    last_error = f"{srv_name}: {str(e)}"
                    log(f"⚠ {srv_name} non disponibile ({str(e)[:120]}). Passo al server successivo...")
                    time.sleep(0.3)

        # If at least one server responded validly with 0 features (e.g., area genuinely has no roads)
        if empty_fallback_geojson is not None:
            log("Avviso: tutti i server raggiungibili confermano 0 strade nell'area selezionata.")
            self._save_geojson_atomic(empty_fallback_geojson, output_path)
            return True, output_path

        log(f"✗ ERRORE OSM: Impossibile scaricare le strade da nessun server. Ultimo errore: {last_error}")
        return False, f"Tutti i server OSM hanno fallito. Ultimo errore: {last_error}"

    def _request_with_ssl_fallback(self, method, url, headers, timeout, params=None, data=None, log=None):
        """Performs HTTP request with automatic SSL verification fallback on certificate errors."""
        try:
            if method == "POST":
                resp = requests.post(url, data=data, headers=headers, timeout=timeout)
            else:
                resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            return resp
        except Exception as e:
            err_str = str(e)
            if any(k in err_str.lower() for k in ("ssl", "certificate", "verify", "handshake")):
                if log:
                    log(f"Avviso SSL su {url}, nuovo tentativo senza verifica certificato...")
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                if method == "POST":
                    return requests.post(url, data=data, headers=headers, timeout=timeout, verify=False)
                else:
                    return requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
            raise

    def _query_overpass_server(self, url, bbox, headers, timeout, use_out_geom=True, log=None):
        """Queries an Overpass API server and validates the returned JSON."""
        south, west, north, east = bbox
        overpass_timeout = max(int(timeout[1]) - 3, 15)

        if use_out_geom:
            # 'out geom;' returns coordinates directly inline on ways (much faster and lighter on Overpass servers)
            query = (
                f"[out:json][timeout:{overpass_timeout}];"
                f"(way[\"highway\"~\"{self.HIGHWAY_REGEX}\"]({south},{west},{north},{east}););"
                f"out geom;"
            )
        else:
            query = (
                f"[out:json][timeout:{overpass_timeout}];"
                f"(way[\"highway\"~\"{self.HIGHWAY_REGEX}\"]({south},{west},{north},{east}););"
                f"out body;>;out skel qt;"
            )

        response = self._request_with_ssl_fallback(
            "POST", url, headers=headers, timeout=timeout, data={"data": query}, log=log
        )

        # Fallback to GET if server rejects POST
        if response.status_code in (400, 405):
            response = self._request_with_ssl_fallback(
                "GET", url, headers=headers, timeout=timeout, params={"data": query}, log=log
            )

        response.raise_for_status()

        try:
            osm_data = response.json()
        except Exception:
            raise RuntimeError("Risposta non in formato JSON valido (possibile pagina HTML di errore/ sovraccarico)")

        # Overpass can return HTTP 200 with a 'remark' field when a query times out or runs out of memory
        remark = osm_data.get("remark", "")
        if remark and any(w in remark.lower() for w in ("error", "timed out", "timeout", "memory", "quota", "busy")):
            raise RuntimeError(f"Errore interno Overpass: {remark}")

        if "elements" not in osm_data:
            raise RuntimeError("Campo 'elements' mancante nella risposta Overpass")

        return osm_data

    def _query_osm_api_v06(self, url, bbox, headers, timeout, log=None, cancel_check=None, depth=0):
        """
        Queries the official OpenStreetMap API v0.6 (/api/0.6/map.json?bbox=west,south,east,north).
        Automatically subdivides the bounding box into 4 quadrants if the area exceeds the node limit.
        """
        south, west, north, east = bbox
        # Prevent excessive recursion
        if depth > 2:
            raise RuntimeError("Area troppo vasta per OSM API v0.6 anche dopo suddivisione")

        # If bbox is larger than 0.20 sq degrees, split proactively
        if (east - west) * (north - south) > 0.20 and depth < 2:
            return self._split_and_query_osm_api_v06(url, bbox, headers, timeout, log, cancel_check, depth)

        params = {"bbox": f"{west},{south},{east},{north}"}
        response = self._request_with_ssl_fallback(
            "GET", url, headers=headers, timeout=timeout, params=params, log=log
        )

        # HTTP 400 on /api/0.6/map means too many nodes (>50,000) in bbox -> split into 2x2 grid
        if response.status_code == 400 and depth < 2:
            if log:
                log("Area densa per OSM API v0.6, suddivisione automatica del riquadro in 4 quadranti...")
            return self._split_and_query_osm_api_v06(url, bbox, headers, timeout, log, cancel_check, depth)

        response.raise_for_status()

        try:
            osm_data = response.json()
        except Exception:
            raise RuntimeError("Risposta OSM API v0.6 non in formato JSON valido")

        if "elements" not in osm_data:
            raise RuntimeError("Campo 'elements' mancante nella risposta OSM API v0.6")

        return osm_data

    def _split_and_query_osm_api_v06(self, url, bbox, headers, timeout, log, cancel_check, depth):
        """Subdivides bbox into 4 quadrants and merges OSM elements."""
        south, west, north, east = bbox
        mid_lat = round((south + north) / 2.0, 6)
        mid_lon = round((west + east) / 2.0, 6)

        quadrants = [
            (south, west, mid_lat, mid_lon),
            (south, mid_lon, mid_lat, east),
            (mid_lat, west, north, mid_lon),
            (mid_lat, mid_lon, north, east),
        ]

        merged_elements = {}
        for q_bbox in quadrants:
            if cancel_check and cancel_check():
                raise RuntimeError("Canceled")
            sub_data = self._query_osm_api_v06(url, q_bbox, headers, timeout, log, cancel_check, depth + 1)
            for el in sub_data.get("elements", []):
                key = (el.get("type"), el.get("id"))
                merged_elements[key] = el

        return {"elements": list(merged_elements.values())}

    def _osm_to_geojson(self, osm_data):
        """
        Converts OSM JSON (supporting both Overpass 'out geom;' inline geometry
        and standard 'node' + 'way' references) into a LineString GeoJSON FeatureCollection.
        Filters ways to valid highway types.
        """
        elements = osm_data.get("elements", [])
        nodes = {
            n["id"]: (n["lon"], n["lat"])
            for n in elements
            if n.get("type") == "node" and "lon" in n and "lat" in n
        }
        features = []

        for el in elements:
            if el.get("type") != "way":
                continue

            tags = el.get("tags", {})
            h_type = tags.get("highway")
            if not h_type:
                continue

            # Filter out non-road highway tags if data came from unfiltered /api/0.6/map.json
            if h_type not in self.VALID_HIGHWAYS and not h_type.endswith("_link"):
                continue

            # 1. Check inline geometry first (from Overpass 'out geom;')
            if "geometry" in el and isinstance(el["geometry"], list):
                coords = [
                    [pt["lon"], pt["lat"]]
                    for pt in el["geometry"]
                    if isinstance(pt, dict) and "lon" in pt and "lat" in pt
                ]
            else:
                # 2. Fallback to node ID lookup (from Overpass 'out body' or OSM API v0.6)
                coords = [
                    list(nodes[node_id])
                    for node_id in el.get("nodes", [])
                    if node_id in nodes
                ]

            if len(coords) < 2:
                continue

            feature = {
                "type": "Feature",
                "id": el.get("id"),
                "properties": tags,
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            }
            features.append(feature)

        return {
            "type": "FeatureCollection",
            "features": features,
        }

    def _save_geojson_atomic(self, geojson, output_path):
        """Writes GeoJSON to a temporary file first and atomically replaces output_path."""
        tmp_path = f"{output_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        os.replace(tmp_path, output_path)

