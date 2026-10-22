# -*- coding: utf-8 -*-
"""
EnviProtocol Dashboard - Project Migration Task
Background task for reprojecting prepared files.
"""

from qgis.core import QgsTask, QgsMessageLog, Qgis

class MigrationTask(QgsTask):
    """Background task to migrate prepared files to the target CRS."""
    
    def __init__(self, em_manager, target_crs_auth):
        super().__init__("Migrazione CRS EnviProtocol", QgsTask.CanCancel)
        self.em_manager = em_manager
        self.target_crs_auth = target_crs_auth
        self.success = False
        self.message = ""

    def run(self):
        try:
            success, msg = self.em_manager.migrate_project_to_target_crs(
                self.target_crs_auth, 
                task=self
            )
            self.success = success
            self.message = msg
            return success
        except Exception as e:
            self.message = str(e)
            return False

    def finished(self, result):
        if result:
            QgsMessageLog.logMessage(f"Migrazione CRS completata con successo: {self.message}", "EnviProtocol", Qgis.Info)
        else:
            QgsMessageLog.logMessage(f"Errore migrazione CRS: {self.message}", "EnviProtocol", Qgis.Warning)
