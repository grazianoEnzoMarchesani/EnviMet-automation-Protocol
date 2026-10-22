# -*- coding: utf-8 -*-
"""
EnviProtocol Dashboard - UI Section Widgets

This package contains modular UI section widgets for the EnviProtocol Dashboard.
"""

from .project_setup import ProjectSetupSection
from .data_acquisition import DataAcquisitionSection
from .envimet_export import ENVImetExportSection
from .sub_area_modification import SubAreaModificationSection
from .attribute_modification import AttributeModificationSection
from .progress_info import ProgressInfoSection
from .envimet_import import ENVImetImportSection

__all__ = [
    'ProjectSetupSection',
    'DataAcquisitionSection',
    'ENVImetExportSection',
    'SubAreaModificationSection',
    'AttributeModificationSection',
    'ProgressInfoSection',
    'ENVImetImportSection'
]
