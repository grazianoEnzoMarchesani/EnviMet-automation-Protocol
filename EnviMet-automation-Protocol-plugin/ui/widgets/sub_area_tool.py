# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsRubberBand, QgsSnapIndicator
from qgis.core import (
    QgsPointXY, QgsGeometry, QgsRectangle, 
    Qgis, QgsPointLocator, QgsMessageLog
)
import math


class SubAreaStatus:
    """Helper to store Sub Area state."""
    def __init__(self, center=QgsPointXY(0,0), width=100.0, height=100.0, rotation=0.0):
        self.center = center
        self.width = width
        self.height = height
        self.rotation = rotation

class SubAreaMapTool(QgsMapTool):
    """
    Map Tool for interactive Sub Area manipulation.
    Handles rendering of the rotated rectangle, grid preview, and dimensions.
    """
    
    # Signals for UI sync (center, width, height, rotation)
    geometryChanged = pyqtSignal(object, float, float, float)
    
    def __init__(self, canvas, max_extent, crs_authid, initial_state=None, name="default", color=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.max_extent = max_extent
        self.max_geom = QgsGeometry.fromRect(max_extent)
        self.crs_authid = crs_authid
        self.name = name
        
        # State: Use provided state or default to center of extent
        if initial_state:
            self.state = initial_state
        else:
            self.state = SubAreaStatus(
                center=max_extent.center(),
                width=max_extent.width() * 0.8,
                height=max_extent.height() * 0.8,
                rotation=0.0
            )
        
        # Determine color based on sub-area name or provided custom color
        if color:
            stroke_color = color
        else:
            from ...core.utils import get_color_for_sub_area
            stroke_color = get_color_for_sub_area(name)
            
        fill_color = QColor(stroke_color.red(), stroke_color.green(), stroke_color.blue(), 45)
        grid_color = QColor(stroke_color.red(), stroke_color.green(), stroke_color.blue(), 70)
        
        # Rendering Items
        self.rubber_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Polygon)
        self.rubber_band.setColor(fill_color)
        self.rubber_band.setSecondaryStrokeColor(stroke_color)
        self.rubber_band.setWidth(2)
        self.rubber_band.setLineStyle(Qt.PenStyle(2)) 
        
        self.grid_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        self.grid_band.setColor(grid_color)
        self.grid_band.setWidth(1)
        self.grid_band.setLineStyle(Qt.PenStyle(3))
        
        self.show_grid = False
        self.dragging = False
        self.snap_internal = True
        self.snap_tolerance = 15
        
        # Snapping setup
        self.snapper = self.canvas.snappingUtils()
        self.snap_indicator = QgsSnapIndicator(self.canvas)
        
        self.update_geometry()

    def update_colors(self, name):
        """Update colors of rubber bands according to the sub-area name."""
        from ...core.utils import get_color_for_sub_area
        self.name = name
        stroke_color = get_color_for_sub_area(name)
        fill_color = QColor(stroke_color.red(), stroke_color.green(), stroke_color.blue(), 45)
        grid_color = QColor(stroke_color.red(), stroke_color.green(), stroke_color.blue(), 70)
        
        self.rubber_band.setColor(fill_color)
        self.rubber_band.setSecondaryStrokeColor(stroke_color)
        self.grid_band.setColor(grid_color)
        self.update_geometry()

    def update_colors_from_color(self, stroke_color):
        """Update colors of rubber bands directly using a QColor instance."""
        fill_color = QColor(stroke_color.red(), stroke_color.green(), stroke_color.blue(), 45)
        grid_color = QColor(stroke_color.red(), stroke_color.green(), stroke_color.blue(), 70)
        
        self.rubber_band.setColor(fill_color)
        self.rubber_band.setSecondaryStrokeColor(stroke_color)
        self.grid_band.setColor(grid_color)
        self.update_geometry()



    def set_params(self, width, height, rotation, grid_size, show_grid, snap_internal=True, snap_tolerance=15):
        """Update params from UI."""
        # Validate constraint before applying
        old_state = (self.state.width, self.state.height, self.state.rotation)
        
        self.state.width = width
        self.state.height = height
        self.state.rotation = rotation
        self.grid_size = grid_size
        self.show_grid = show_grid
        self.snap_internal = snap_internal
        self.snap_tolerance = snap_tolerance
        
        if not self._check_constraints():
            # Rollback if invalid
            self.state.width, self.state.height, self.state.rotation = old_state
            return False
            
        self.update_geometry()
        # Emit change to sync UI
        self.geometryChanged.emit(self.state.center, self.state.width, self.state.height, self.state.rotation)
        return True

    def _check_constraints(self):
        """Verify if current state is within max_geom (with a tiny tolerance)."""
        geom = self._get_geometry()
        # Add a 10cm buffer to account for floating point precision in UI SpinBoxes
        is_inside = self.max_geom.buffer(0.1, 5).contains(geom)
        if not is_inside and not self.dragging:
            QgsMessageLog.logMessage(
                f"Avviso: La sub area '{self.name}' si trova parzialmente o totalmente fuori dal perimetro AOI.",
                "EnviProtocol",
                Qgis.Warning
            )
        return True

    @staticmethod
    def get_geometry_from_state(state):
        """Standard geometry generation from a SubAreaStatus state."""
        import math
        from qgis.core import QgsPointXY, QgsGeometry
        angle_rad = math.radians(state.rotation)
        dx = state.width / 2.0
        dy = state.height / 2.0
        cx, cy = state.center.x(), state.center.y()
        
        corners = [
            (-dx, -dy), (dx, -dy), (dx, dy), (-dx, dy)
        ]
        
        pts = []
        for x, y in corners:
            nx = x * math.cos(angle_rad) - y * math.sin(angle_rad)
            ny = x * math.sin(angle_rad) + y * math.cos(angle_rad)
            pts.append(QgsPointXY(cx + nx, cy + ny))
            
        return QgsGeometry.fromPolygonXY([pts])

    def _get_geometry(self):
        """Generates rotated rectangle geometry."""
        return self.get_geometry_from_state(self.state)

    def update_geometry(self, force_grid=False):
        """Refresh all canvas items."""
        geom = self._get_geometry()
        self.rubber_band.setToGeometry(geom, None)
        
        # Optimization: skip grid rendering during dragging to keep UI fluid
        if self.show_grid and (force_grid or not self.dragging):
            self._update_grid(geom)
        else:
            self.grid_band.reset()
            

    def _update_grid(self, geom):
        """Calculates and renders the internal grid lines using MultiLine geometry."""
        self.grid_band.reset()
        if self.grid_size <= 0: return
        
        # Safety Limit: if grid is way too dense (e.g. > 500 lines) skip rendering
        if (self.state.width / self.grid_size) > 500 or (self.state.height / self.grid_size) > 500:
            return
        
        # Logic: generate lines parallel to edges
        angle_rad = math.radians(self.state.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        w = self.state.width
        h = self.state.height
        cx = self.state.center.x()
        cy = self.state.center.y()
        
        lines = []
        
        # Vertical lines (parallel to Height axis)
        num_v = int(w / self.grid_size)
        start_x = -w/2.0
        for i in range(1, num_v + 1):
            lx = start_x + i * self.grid_size
            if lx >= w/2.0: break
            
            p1_rel = (lx, -h/2.0)
            p2_rel = (lx, h/2.0)
            
            # Rotate
            p1 = QgsPointXY(cx + p1_rel[0]*cos_a - p1_rel[1]*sin_a, cy + p1_rel[0]*sin_a + p1_rel[1]*cos_a)
            p2 = QgsPointXY(cx + p2_rel[0]*cos_a - p2_rel[1]*sin_a, cy + p2_rel[0]*sin_a + p2_rel[1]*cos_a)
            
            lines.append([p1, p2])

        # Horizontal lines (parallel to Width axis)
        num_h = int(h / self.grid_size)
        start_y = -h/2.0
        for i in range(1, num_h + 1):
            ly = start_y + i * self.grid_size
            if ly >= h/2.0: break
            
            p1_rel = (-w/2.0, ly)
            p2_rel = (w/2.0, ly)
            
            p1 = QgsPointXY(cx + p1_rel[0]*cos_a - p1_rel[1]*sin_a, cy + p1_rel[0]*sin_a + p1_rel[1]*cos_a)
            p2 = QgsPointXY(cx + p2_rel[0]*cos_a - p2_rel[1]*sin_a, cy + p2_rel[0]*sin_a + p2_rel[1]*cos_a)
            
            lines.append([p1, p2])

        if lines:
            from qgis.core import QgsGeometry
            multi_line = QgsGeometry.fromMultiPolylineXY(lines)
            self.grid_band.setToGeometry(multi_line, None)


    def canvasPressEvent(self, event):
        """Handle dragging the sub area."""
        if event.button() == Qt.LeftButton:
            click_pos = event.pos()
            map_pos = self.toMapCoordinates(click_pos)
            
            # Get current geometric points (corners + center) for grab-point snapping
            rect_geom = self._get_geometry()
            target_grab_point = None
            
            if self.snap_internal:
                # corners from polygon (first 4 points)
                points_to_check = rect_geom.asPolygon()[0][:4]
                points_to_check.append(self.state.center)
                
                min_dist = self.snap_tolerance + 1
                
                for pt in points_to_check:
                    canvas_pt = self.toCanvasCoordinates(pt)
                    dist = math.sqrt((canvas_pt.x() - click_pos.x())**2 + (canvas_pt.y() - click_pos.y())**2)
                    if dist < self.snap_tolerance and dist < min_dist:
                        min_dist = dist
                        target_grab_point = pt
            
            # Start dragging
            if target_grab_point:
                # User clicked near a corner or center: snap the drag start to that exact point
                self.dragging = True
                self.drag_start = target_grab_point
                self.start_center = self.state.center
            elif rect_geom.contains(QgsPointXY(map_pos)):
                # User clicked inside the area but not near a corner: use raw click point
                self.dragging = True
                self.drag_start = map_pos
                self.start_center = self.state.center
            else:
                self.dragging = False

    def canvasMoveEvent(self, event):
        # Determine current snap point
        snap_match = self.snapper.snapToMap(event.mapPoint())
        self.snap_indicator.setMatch(snap_match)
        
        if hasattr(self, 'dragging') and self.dragging:
            # Use snapped point if valid, otherwise regular map point
            pos = snap_match.point() if snap_match.isValid() else event.mapPoint()
            
            dx = pos.x() - self.drag_start.x()
            dy = pos.y() - self.drag_start.y()
            
            new_center = QgsPointXY(self.start_center.x() + dx, self.start_center.y() + dy)
            old_center = self.state.center
            self.state.center = new_center
            
            if not self._check_constraints():
                self.state.center = old_center
            else:
                self.update_geometry()
                self.geometryChanged.emit(self.state.center, self.state.width, self.state.height, self.state.rotation)

    def canvasReleaseEvent(self, event):
        self.dragging = False
        self.update_geometry(force_grid=True)
        # Log constraint warning when dragging ends
        geom = self._get_geometry()
        is_inside = self.max_geom.buffer(0.1, 5).contains(geom)
        if not is_inside:
            QgsMessageLog.logMessage(
                f"Avviso: La sub area '{self.name}' si trova parzialmente o totalmente fuori dal perimetro AOI dopo lo spostamento.",
                "EnviProtocol",
                Qgis.Warning
            )

    def deactivate(self):
        self.rubber_band.reset()
        self.grid_band.reset()
        self.snap_indicator.setMatch(QgsPointLocator.Match()) # Clear snap feedback
        super().deactivate()
