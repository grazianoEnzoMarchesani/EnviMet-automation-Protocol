# -*- coding: utf-8 -*-
"""
EnviProtocol Plugin - Dependency Verification & Diagnostic Helper for QGIS.
Run this script inside the QGIS Python Console (Plugins -> Python Console)
to verify your environment or optionally install advanced ML dependencies.
"""

import sys
import subprocess
import os

def check_or_install_dependencies():
    from qgis.core import QgsMessageLog, Qgis
    from qgis.utils import iface

    def log(msg, level=Qgis.Info):
        print(msg)
        QgsMessageLog.logMessage(str(msg), 'EnviProtocol', level)
        if iface:
            iface.messageBar().pushMessage("EnviProtocol", str(msg), level=level, duration=4)

    log("=== EnviProtocol: Verifica Ambiente e Dipendenze ===")

    # 1. Core dependencies (normally bundled directly with QGIS)
    core_packages = ["requests", "urllib3", "numpy"]
    missing_core = []

    for pkg in core_packages:
        try:
            __import__(pkg)
            log(f"  [OK] {pkg} è presente.")
        except ImportError:
            missing_core.append(pkg)
            log(f"  [MANCANTE] {pkg} non trovato!", Qgis.Warning)

    python_exe = sys.executable
    if sys.platform == 'darwin' and "QGIS" in python_exe and not python_exe.endswith("python3"):
        base = os.path.dirname(python_exe)
        potential = os.path.join(base, "python3")
        if os.path.exists(potential):
            python_exe = potential

    env = os.environ.copy()

    # Attempt to install missing core packages if any
    if missing_core:
        log(f"Tentativo di installazione automatica per: {missing_core}...", Qgis.Warning)
        for pkg in missing_core:
            try:
                cmd = [python_exe, "-m", "pip", "install", "--prefer-binary", pkg]
                res = subprocess.run(cmd, capture_output=True, text=True, env=env)
                if res.returncode == 0:
                    log(f"  ✓ {pkg} installato con successo!")
                else:
                    # Fallback user mode
                    cmd_user = [python_exe, "-m", "pip", "install", "--user", "--prefer-binary", pkg]
                    res_user = subprocess.run(cmd_user, capture_output=True, text=True, env=env)
                    if res_user.returncode == 0:
                        log(f"  ✓ {pkg} installato (modalità utente)!")
                    else:
                        log(f"  ✗ Errore nell'installazione di {pkg}: {res.stderr or res.stdout}", Qgis.Critical)
            except Exception as e:
                log(f"  ✗ Errore imprevisto: {e}", Qgis.Critical)
    else:
        log("✓ Tutte le dipendenze CORE del plugin sono presenti e operative!", Qgis.Success)

    # 2. Check optional ML dependencies (for standalone scripts in 'script modifica raster envimet')
    log("\n--- Controllo Dipendenze Opzionali per Script ML / Post-Processing ---")
    ml_packages = ["pandas", "sklearn", "joblib", "matplotlib"]
    missing_ml = []

    for pkg in ml_packages:
        try:
            __import__(pkg)
            log(f"  [OK] {pkg} (opzionale) è presente.")
        except ImportError:
            missing_ml.append(pkg)
            log(f"  [INFO] {pkg} (opzionale per script ML) non installato.")

    if not missing_ml:
        log("✓ Anche le dipendenze opzionali di Machine Learning sono pronte!", Qgis.Success)
    else:
        log(f"Nota: Se intendi utilizzare gli script avanzati di Machine Learning, puoi installare: {missing_ml}")

    log("=== CONTROLLO COMPLETATO ===")

if __name__ == '__main__':
    check_or_install_dependencies()
