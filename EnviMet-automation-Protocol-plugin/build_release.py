# -*- coding: utf-8 -*-
"""
EnviProtocol Release Packager for QGIS.
Creates a clean, production-ready 'EnviProtocol.zip' in the 'dist/' folder,
structured specifically for direct installation via QGIS 'Install from ZIP'.
"""

import os
import sys
import zipfile
import shutil

def build_zip():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    
    zip_path = os.path.join(dist_dir, "EnviProtocol.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    # Top-level folder inside the ZIP (as expected by QGIS Plugin Manager)
    root_folder_in_zip = "EnviProtocol"

    # Core files to include
    top_level_files = [
        "metadata.txt",
        "__init__.py",
        "main.py",
        "icon.png",
        "icon.jpg",
        "requirements.txt",
        "install_deps_qgis.py",
        "README.md",
        "CITATION.cff",
        ".zenodo.json"
    ]

    # Directories to include
    include_dirs = [
        "core",
        "ui",
        "data",
        "EnviReader",
        "script modifica raster envimet"
    ]

    # Exclusions
    exclude_exts = {".pyc", ".DS_Store", ".log", ".tmp"}
    exclude_dirs = {"__pycache__", ".git", ".agents", ".vscode", ".idea"}

    print("=" * 60)
    print("Packing EnviProtocol for QGIS Plugin Manager...")
    print("=" * 60)

    count_files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Add top-level files
        for filename in top_level_files:
            file_path = os.path.join(base_dir, filename)
            if os.path.exists(file_path):
                arc_path = os.path.join(root_folder_in_zip, filename)
                zf.write(file_path, arc_path)
                count_files += 1
                print(f"  + {filename}")
            else:
                print(f"  - Saltato (non trovato): {filename}")

        # 2. Add subdirectories
        for d in include_dirs:
            dir_full = os.path.join(base_dir, d)
            if not os.path.exists(dir_full):
                print(f"  - Cartella non trovata: {d}")
                continue

            for root, dirs, files in os.walk(dir_full):
                # Prune excluded directories in-place
                dirs[:] = [sub for sub in dirs if sub not in exclude_dirs]

                for file in files:
                    ext = os.path.splitext(file)[1]
                    if ext in exclude_exts or file == ".DS_Store":
                        continue

                    full_path = os.path.join(root, file)
                    rel_to_base = os.path.relpath(full_path, base_dir)
                    arc_path = os.path.join(root_folder_in_zip, rel_to_base)
                    zf.write(full_path, arc_path)
                    count_files += 1

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print("-" * 60)
    print(f"[OK] Pacchetto creato con successo!")
    print(f"  Percorso: {zip_path}")
    print(f"  File inclusi: {count_files}")
    print(f"  Dimensione: {size_mb:.2f} MB")
    print("=" * 60)
    print("Questo file ZIP puo essere caricato direttamente come ASSET")
    print("nella pagina di Release GitHub (es. Release v2.0.0).")
    print("L'utente potra scaricarlo e fare: QGIS -> Plugin -> Installa da ZIP!")

if __name__ == "__main__":
    build_zip()
