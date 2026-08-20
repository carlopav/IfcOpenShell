# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.
#
# This file was generated with the assistance of an AI coding tool.

"""Click handles on the vertices of a DIMENSION annotation."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from math import atan2, degrees
from typing import NamedTuple

import bpy
import ifcopenshell.util.element
from mathutils import Matrix, Vector, geometry

import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore
from bonsai.bim.module.drawing.data import DrawingsData
from bonsai.bim.module.drawing.gizmos import X3DISC, apply_transform_modal_draw_gate
from bonsai.bim.module.drawing.helper import format_distance
from bonsai.bim.module.model.decorator import PolylineDecorator
from bonsai.bim.module.model.polyline import PolylineOperator

# Only plain linear dimensions get vertex handles. RADIUS / DIAMETER / ANGLE are
# curve annotations too, but their points carry different meanings.
DIMENSION_OBJECT_TYPE = "DIMENSION"

# Matches the ``UglyDotGizmo`` handle in ``ExtrusionWidget`` so both dot handles
# read identically. Deliberately *not* SNAP_POINT_COLOR — the snap indicator
# appears during the same placement and has to stay distinguishable.
HANDLE_SCALE = 0.1
HANDLE_ALPHA = 0.5
HANDLE_ALPHA_HIGHLIGHT = 1.0

# The world plane each annotation plane maps onto, indexed by the axis its
# normal is closest to.
PLANE_METHODS = ("YZ", "XZ", "XY")

INSTRUCTIONS = {
    "Distance Input": {"icons": True, "keys": ["EVENT_D"]},
    "Modify Snap Point": {"icons": True, "keys": ["EVENT_M"]},
    "Confirm": {"icons": True, "keys": ["MOUSE_LMB"]},
    "Cancel": {"icons": True, "keys": ["MOUSE_RMB", "EVENT_ESC"]},
}


class CurvePointRef(NamedTuple):
    """One editable vertex of a dimension annotation, in world space."""

    spline_index: int
    point_index: int
    world_co: Vector


@dataclass
class PendingVertexMove:
    """The vertex placement being previewed.

    ``MoveDimensionVertex`` and ``GizmoDimensionVertexEdition`` have no way to
    talk to each other, so a module-level instance carries the preview
    out-of-band, the same way ``gizmos.GizmoModalContext`` does.
    """

    is_active: bool = False
    anchor_world: Vector = field(default_factory=Vector)
    axis_direction: Vector = field(default_factory=lambda: Vector((1.0, 0.0, 0.0)))
    plane_normal: Vector = field(default_factory=lambda: Vector((0.0, 0.0, 1.0)))
    location: Vector = field(default_factory=Vector)

    def start(self, anchor_world: Vector, location: Vector, axis_direction: Vector, plane_normal: Vector) -> None:
        self.is_active = True
        self.anchor_world = anchor_world.copy()
        self.location = location.copy()
        self.axis_direction = axis_direction.copy()
        self.plane_normal = plane_normal.copy()

    def clear(self) -> None:
        self.is_active = False


_pending_vertex_move = PendingVertexMove()


def get_pending_vertex_move() -> PendingVertexMove:
    """The vertex placement being previewed, active or not."""
    return _pending_vertex_move


def preview_dimension(anchor_world: Vector, location: Vector, axis_direction: Vector) -> tuple[Vector, float]:
    """The direction and length of the preview line drawn from the anchor.

    The vertex is locked to ``axis_direction``, so its offset along that axis is
    the measurement; the line is always drawn away from the anchor.
    """
    distance = (location - anchor_world).dot(axis_direction)
    return (axis_direction if distance >= 0 else -axis_direction), abs(distance)


def preview_gizmo_matrix(location: Vector, direction: Vector, plane_normal: Vector) -> Matrix:
    """Place a ``BIM_GT_gizmo_dimension`` at ``location`` along ``direction``.

    That gizmo draws along its local +X; keeping local Z on the drawing plane
    normal keeps its arrows and label in the plane of the drawing.
    """
    x_axis = direction.normalized()
    z_axis = plane_normal.normalized()
    y_axis = z_axis.cross(x_axis)
    matrix = Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
    matrix.translation = location
    return matrix


def project_ray_to_annotation_plane(matrix_world, ray_origin: Vector, ray_direction: Vector) -> Vector | None:
    """Intersect a view ray with the annotation's own plane.

    Annotation objects are placed on the drawing camera's plane, so their local
    XY plane *is* the drawing plane and local Z is its normal. Returns None when
    the ray runs parallel to the plane.
    """
    plane_co = matrix_world.translation
    plane_no = matrix_world.to_3x3().col[2].normalized()
    return geometry.intersect_line_plane(ray_origin, ray_origin + ray_direction, plane_co, plane_no)


def project_point_to_annotation_plane(matrix_world, point: Vector) -> Vector:
    """Drop a world-space point perpendicularly onto the annotation's plane.

    Snapping targets model vertices at arbitrary depth; annotations have to stay
    on the drawing plane, so the snapped result is flattened onto it.
    """
    plane_co = matrix_world.translation
    plane_no = matrix_world.to_3x3().col[2].normalized()
    return point - plane_no * (point - plane_co).dot(plane_no)


def annotation_plane_method(matrix_world) -> str:
    """The polyline snap plane ("XY", "XZ" or "YZ") for an annotation plane."""
    normal = matrix_world.to_3x3().col[2]
    return PLANE_METHODS[max(range(3), key=lambda axis: abs(normal[axis]))]


def axis_snap_angle(plane_method: str, direction: Vector) -> float:
    """The locked angle, in degrees, that makes ``Snap.snap_on_axis`` follow ``direction``.

    Each snap plane measures its angle from a different pair of world axes.
    """
    if plane_method == "XZ":
        return degrees(atan2(direction.z, direction.x))
    if plane_method == "YZ":
        return degrees(atan2(direction.z, direction.y))
    return degrees(atan2(direction.y, direction.x))


def neighbour_point_index(point_count: int, point_index: int) -> int | None:
    """The vertex a moved one is measured against, or None if there is no other."""
    if point_count < 2:
        return None
    return point_index - 1 if point_index else 1


def dimension_axis_direction(obj: bpy.types.Object, spline_index: int, point_index: int) -> Vector:
    """The world direction a dimension vertex is allowed to slide along."""
    points = obj.data.splines[spline_index].points
    neighbour = neighbour_point_index(len(points), point_index)
    if neighbour is not None:
        direction = Vector(points[point_index].co[:3]) - Vector(points[neighbour].co[:3])
        if direction.length > 1e-6:
            return (obj.matrix_world.to_3x3() @ direction).normalized()
    # Dimensions are drawn along the annotation's local Y (see
    # ``Annotator.get_placeholder_coords``), which is the only axis left to
    # follow once the two vertices coincide.
    return obj.matrix_world.to_3x3().col[1].normalized()


def format_dimension_value(length: float) -> str:
    """Format a length the way the drawing's own dimension label does."""
    pset_data = DrawingsData.data.get("active_drawing_pset_data") or {}
    precision = pset_data.get("MetricPrecision") or pset_data.get("ImperialPrecision")
    return format_distance(length, precision=precision, decimal_places=pset_data.get("DecimalPlaces"))


def is_dimension_annotation(obj: bpy.types.Object | None) -> bool:
    """True when ``obj`` is an IfcAnnotation curve of predefined type DIMENSION."""
    if obj is None or obj.type != "CURVE":
        return False
    element = tool.Ifc.get_entity(obj)
    if element is None or not element.is_a("IfcAnnotation"):
        return False
    return ifcopenshell.util.element.get_predefined_type(element) == DIMENSION_OBJECT_TYPE


def curve_point_world_positions(obj: bpy.types.Object) -> list[CurvePointRef]:
    """Every point of every spline on a dimension annotation, in world space."""
    matrix_world = obj.matrix_world
    positions: list[CurvePointRef] = []
    for spline_index, spline in enumerate(obj.data.splines):
        for point_index, point in enumerate(spline.points):
            world_co = matrix_world @ Vector(point.co[:3])
            positions.append(CurvePointRef(spline_index, point_index, world_co))
    return positions


def set_curve_point_world(obj: bpy.types.Object, spline_index: int, point_index: int, world_co: Vector) -> None:
    """Move one curve point to a world-space location, preserving its weight."""
    point = obj.data.splines[spline_index].points[point_index]
    local_co = obj.matrix_world.inverted() @ world_co
    point.co = (local_co.x, local_co.y, local_co.z, point.co[3])


class MoveDimensionVertex(bpy.types.Operator, PolylineOperator, tool.Ifc.Operator):
    """Place a dimension vertex with a second click, on Bonsai's snaps.

    The vertex is locked to the line the dimension already measures, so the
    dimension stays in line with itself. While placing, the pending measurement
    is shown by the preview gizmo; the annotation itself is only rewritten on
    confirm, because rewriting the curve per event invalidates the datablock and
    makes ``DecoratorData`` reload every visible object.
    """

    bl_idname = "bim.move_dimension_vertex"
    bl_label = "Move Dimension Vertex"
    bl_description = "Move a dimension vertex along the dimension axis"
    bl_options = {"REGISTER", "UNDO"}

    obj: bpy.props.StringProperty(options={"SKIP_SAVE"})
    spline_index: bpy.props.IntProperty(options={"SKIP_SAVE"})
    point_index: bpy.props.IntProperty(options={"SKIP_SAVE"})

    def __init__(self, *args, **kwargs):
        bpy.types.Operator.__init__(self, *args, **kwargs)
        PolylineOperator.__init__(self)
        # Distance is the only editable input: typing an X or a Y would take the
        # vertex off the dimension line it is locked to.
        self.input_options = ["D"]
        self.input_ui = tool.Polyline.create_input_ui(input_options=self.input_options)
        self.initial_world_co = Vector()
        self.anchor_world = Vector()
        self.has_moved = False

    def invoke(self, context, event):
        annotation = bpy.data.objects.get(self.obj)
        if not is_dimension_annotation(annotation):
            return {"CANCELLED"}
        points = annotation.data.splines[self.spline_index].points
        self.initial_world_co = annotation.matrix_world @ Vector(points[self.point_index].co[:3])
        neighbour = neighbour_point_index(len(points), self.point_index)
        if neighbour is None:
            self.anchor_world = self.initial_world_co.copy()
        else:
            self.anchor_world = annotation.matrix_world @ Vector(points[neighbour].co[:3])
        PolylineOperator.invoke(self, context, event)
        self.lock_to_dimension_axis(context, event, annotation)
        return {"RUNNING_MODAL"}

    def lock_to_dimension_axis(self, context, event, annotation):
        """Anchor the polyline on the opposite vertex and lock it to the dimension line."""
        axis_direction = dimension_axis_direction(annotation, self.spline_index, self.point_index)
        plane_normal = annotation.matrix_world.to_3x3().col[2].normalized()
        _pending_vertex_move.start(self.anchor_world, self.initial_world_co, axis_direction, plane_normal)
        self.input_ui.set_value("X", self.anchor_world.x)
        self.input_ui.set_value("Y", self.anchor_world.y)
        self.input_ui.set_value("Z", self.anchor_world.z)
        tool.Polyline.insert_polyline_point(self.input_ui, self.tool_state)
        # Only set afterwards: insert_polyline_point flattens the point onto the
        # plane origin, which is the anchor itself only once the anchor exists.
        self.tool_state.plane_method = annotation_plane_method(annotation.matrix_world)
        self.tool_state.lock_axis = True
        self.tool_state.snap_angle = axis_snap_angle(self.tool_state.plane_method, axis_direction)
        detected_snaps = tool.Snap.detect_snapping_points(context, event, self.objs_2d_bbox, self.tool_state)
        self.snapping_points = tool.Snap.select_snapping_points(context, event, self.tool_state, detected_snaps)
        tool.Polyline.calculate_distance_and_angle(context, self.input_ui, self.tool_state)
        PolylineDecorator.update(event, self.tool_state, self.input_ui, self.snapping_points[0])
        tool.Blender.update_viewport()

    def pending_location(self, annotation) -> Vector:
        """Resolve where the vertex would land and hand it to the preview gizmo."""
        coordinates = [self.input_ui.get_number_value(axis) for axis in ("X", "Y", "Z")]
        if not all(isinstance(coordinate, float) for coordinate in coordinates):
            return self.initial_world_co
        # Snaps land on model geometry at any depth; the vertex may not leave
        # the drawing plane.
        location = project_point_to_annotation_plane(annotation.matrix_world, Vector(coordinates))
        _pending_vertex_move.location = location
        return location

    def cleanup(self, context) -> None:
        _pending_vertex_move.clear()
        tool.Polyline.clear_polyline()
        context.workspace.status_text_set(text=None)
        PolylineDecorator.uninstall()
        tool.Blender.update_viewport()

    def modal(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="MODAL")

    def _modal(self, context, event):
        annotation = bpy.data.objects.get(self.obj)
        if annotation is None:
            self.cleanup(context)
            return {"CANCELLED"}

        PolylineDecorator.update(event, self.tool_state, self.input_ui, self.snapping_points[0])
        tool.Blender.update_viewport()

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            self.handle_mouse_move(context, event)
            return {"PASS_THROUGH"}

        self.handle_mouse_move(context, event)
        self.handle_snap_selection(context, event)
        self.handle_keyboard_input(context, event)
        location = self.pending_location(annotation)
        length = (location - self.anchor_world).length
        self.handle_instructions(context, INSTRUCTIONS, [f"Length: {format_dimension_value(length)}"], overwrite=True)

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            # The click that launched the gizmo must not also place the vertex.
            self.has_moved = True

        if event.value == "RELEASE" and (
            event.type in {"RET", "NUMPAD_ENTER"} or (self.has_moved and event.type == "LEFTMOUSE")
        ):
            if self.tool_state.is_input_on:
                self.recalculate_inputs(context)
                location = self.pending_location(annotation)
            set_curve_point_world(annotation, self.spline_index, self.point_index, location)
            bpy.ops.bim.update_representation(obj=annotation.name)
            self.cleanup(context)
            return {"FINISHED"}

        if event.value == "RELEASE" and event.type == "RIGHTMOUSE":
            self.cleanup(context)
            return {"CANCELLED"}

        cancel = self.handle_cancelation(context, event)
        if cancel is not None:
            # The annotation was never touched, so cancelling only drops the preview.
            _pending_vertex_move.clear()
            tool.Blender.update_viewport()
            return cancel

        return {"RUNNING_MODAL"}


class GizmoDimensionVertex(bpy.types.Gizmo):
    """A dot on one vertex of a DIMENSION annotation.

    Clicking it starts ``bim.move_dimension_vertex``, which takes the second
    click to place the vertex.
    """

    bl_idname = "BIM_GT_gizmo_dimension_vertex"

    __slots__ = ("custom_shape",)

    def setup(self) -> None:
        self.custom_shape = self.new_custom_shape(type="TRIS", verts=X3DISC)

    def draw(self, context: bpy.types.Context) -> None:
        self.draw_custom_shape(self.custom_shape)

    def draw_select(self, context: bpy.types.Context, select_id: int) -> None:
        self.draw_custom_shape(self.custom_shape, select_id=select_id)


class GizmoDimensionVertexEdition(bpy.types.GizmoGroup):
    """Vertex handles for the active DIMENSION annotation, plus the placement preview."""

    bl_idname = "OBJECT_GGT_bim_dimension_vertex_edition"
    bl_label = "Dimension Vertex Editing Gizmo"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    # SHOW_MODAL_ALL: without it the group is not drawn while
    # bim.move_dimension_vertex runs, so its preview would never appear.
    bl_options = {"3D", "PERSISTENT", "SHOW_MODAL_ALL"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        # Object mode only — in edit mode Blender's own vertex tools apply and
        # the handles would fight them for clicks.
        if context.mode != "OBJECT":
            return False
        return is_dimension_annotation(context.active_object)

    def get_props(self, obj: bpy.types.Object | None) -> PendingVertexMove:
        # BIM_GT_gizmo_dimension only calls text_formatter when its group hands
        # it props; the pending move is all the preview label needs.
        return get_pending_vertex_move()

    def setup(self, context: bpy.types.Context) -> None:
        # target_set_operator allocates a fresh handle on every call, so the
        # handles are kept and only their properties are rewritten per refresh.
        self.op_props = []
        self.handles = []
        self.preview = self._new_preview()
        self._sync(context)

    def refresh(self, context: bpy.types.Context) -> None:
        self._sync(context)

    def draw_prepare(self, context: bpy.types.Context) -> None:
        # SHOW_MODAL_ALL keeps the group drawn during a Blender transform modal
        # too, but refresh() does not run then — without this gate the handles
        # would hang at stale positions while G/R/S drags matrix_world. Same
        # gate the parametric groups use; it ignores our own polyline modal.
        if apply_transform_modal_draw_gate(self, context):
            return
        # refresh() does not run while a modal operator does, so the preview
        # follows the mouse from here.
        self._update_preview()

    def _new_preview(self) -> bpy.types.Gizmo:
        """The read-only dimension line showing the vertex being placed."""
        prefs = tool.Blender.get_addon_preferences()
        gizmo = self.gizmos.new("BIM_GT_gizmo_dimension")
        gizmo.gizmo_group = self
        gizmo.text_formatter = lambda props, value: format_dimension_value(value)
        gizmo.color = gizmo.color_highlight = tuple(prefs.decorations_colour[:3])
        gizmo.alpha = gizmo.alpha_highlight = 1.0
        gizmo.use_draw_modal = True
        gizmo.use_draw_scale = False
        gizmo.show_start_arrow = True
        gizmo.show_end_arrow = True
        # No move_get_cb / move_set_cb, and unselectable: the operator owns the
        # interaction, and a clickable preview would steal its second click.
        gizmo.hide_select = True
        gizmo.hide = True
        return gizmo

    def _sync(self, context: bpy.types.Context) -> None:
        obj = context.active_object
        # refresh() can fire before poll() re-runs after the active object
        # changes, and reading .splines off a non-curve would raise.
        if not is_dimension_annotation(obj):
            return
        positions = curve_point_world_positions(obj)

        # Rebuild wholesale when the vertex count changes (edit-mode add/remove).
        # One extra gizmo is the shared preview.
        if len(self.gizmos) != len(positions) + 1:
            theme = context.preferences.themes[0].user_interface
            self.gizmos.clear()
            self.op_props = []
            self.handles = []
            self.preview = self._new_preview()
            for _ in positions:
                gizmo = self.gizmos.new(GizmoDimensionVertex.bl_idname)
                gizmo.color = gizmo.color_highlight = tuple(theme.gizmo_primary)
                gizmo.alpha = HANDLE_ALPHA
                gizmo.alpha_highlight = HANDLE_ALPHA_HIGHLIGHT
                gizmo.scale_basis = HANDLE_SCALE
                self.handles.append(gizmo)
                self.op_props.append(gizmo.target_set_operator(MoveDimensionVertex.bl_idname))

        for gizmo, op_props, reference in zip(self.handles, self.op_props, positions):
            gizmo.matrix_basis = Matrix.Translation(reference.world_co)
            op_props.obj = obj.name
            op_props.spline_index = reference.spline_index
            op_props.point_index = reference.point_index

    def _update_preview(self) -> None:
        pending = get_pending_vertex_move()
        self.preview.hide = not pending.is_active
        for handle in self.handles:
            # The handles mark the vertices the preview is replacing, and they
            # stay put until the curve is written on confirm.
            handle.hide = pending.is_active
        if not pending.is_active:
            return
        direction, length = preview_dimension(pending.anchor_world, pending.location, pending.axis_direction)
        self.preview.matrix_basis = preview_gizmo_matrix(pending.anchor_world, direction, pending.plane_normal)
        self.preview.set_dimension_length(length)
