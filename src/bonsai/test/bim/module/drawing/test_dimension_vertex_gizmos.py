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

"""Unit tests for the DIMENSION annotation vertex gizmos."""

import types
from math import radians
from types import SimpleNamespace

import bpy
import pytest
from mathutils import Matrix, Vector

from bonsai.bim.module.drawing.dimension_vertex_gizmos import (
    GizmoDimensionVertex,
    GizmoDimensionVertexEdition,
    MoveDimensionVertex,
    annotation_plane_method,
    axis_snap_angle,
    curve_point_world_positions,
    dimension_axis_direction,
    format_dimension_value,
    get_pending_vertex_move,
    is_dimension_annotation,
    neighbour_point_index,
    preview_dimension,
    preview_gizmo_matrix,
    project_point_to_annotation_plane,
    project_ray_to_annotation_plane,
    set_curve_point_world,
)

pytestmark = pytest.mark.drawing


@pytest.fixture(autouse=True)
def _require_real_bpy():
    if not isinstance(bpy, types.ModuleType) or hasattr(bpy, "_mock_name"):
        pytest.skip("requires real Blender (bpy is mocked or absent)")


@pytest.fixture
def dimension_curve():
    """A two-point POLY curve offset from the origin, matching how
    ``Annotator.add_line_to_annotation`` builds a DIMENSION annotation."""
    curve = bpy.data.curves.new("TestDim", type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co = (0.0, 0.0, 0.0, 1.0)
    spline.points[1].co = (2.0, 0.0, 0.0, 1.0)
    obj = bpy.data.objects.new("TestDim", curve)
    obj.matrix_world = Matrix.Translation((10.0, 0.0, 5.0))
    yield obj
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curve)


@pytest.fixture
def meters_length_unit():
    """Pin the scene to whole meters so formatted output is not left to
    Blender's adaptive unit picking."""
    unit_settings = bpy.context.scene.unit_settings
    previous = unit_settings.length_unit
    unit_settings.length_unit = "METERS"
    yield
    unit_settings.length_unit = previous


@pytest.fixture
def mesh_object():
    mesh = bpy.data.meshes.new("TestMesh")
    obj = bpy.data.objects.new("TestMesh", mesh)
    yield obj
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(mesh)


@pytest.fixture
def link_ifc_entity(monkeypatch):
    """Attach real IfcAnnotation entities to Blender objects.

    Uses a genuine ifcopenshell file rather than a stub so the predefined-type
    lookup exercises the real ObjectType fallback path.
    """
    import ifcopenshell

    import bonsai.tool as tool

    ifc_file = ifcopenshell.file(schema="IFC4")
    by_object_name: dict[str, object] = {}

    monkeypatch.setattr(tool.Ifc, "get_entity", staticmethod(lambda obj: by_object_name.get(obj.name)))

    def link(obj, *, object_type: str, ifc_class: str = "IfcAnnotation"):
        element = ifc_file.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(), ObjectType=object_type)
        by_object_name[obj.name] = element
        return element

    return link


def test_projects_ray_onto_the_annotation_plane():
    """The annotation's local XY plane is the drawing plane, so a drag must
    resolve to a point on it rather than anywhere along the view ray."""
    annotation_matrix = Matrix.Translation((0.0, 0.0, 2.0))

    hit = project_ray_to_annotation_plane(
        annotation_matrix, ray_origin=Vector((1.0, 3.0, 10.0)), ray_direction=Vector((0.0, 0.0, -1.0))
    )

    assert hit is not None
    assert hit.x == pytest.approx(1.0)
    assert hit.y == pytest.approx(3.0)
    assert hit.z == pytest.approx(2.0)


def test_reports_every_curve_point_in_world_space(dimension_curve):
    """Handles are placed in world space, but curve points are stored local to
    the annotation object, so the object transform has to be applied."""
    positions = curve_point_world_positions(dimension_curve)

    assert [(p.spline_index, p.point_index) for p in positions] == [(0, 0), (0, 1)]
    assert positions[0].world_co.x == pytest.approx(10.0)
    assert positions[0].world_co.z == pytest.approx(5.0)
    assert positions[1].world_co.x == pytest.approx(12.0)


def test_writes_a_dragged_point_back_into_object_local_space(dimension_curve):
    """The drag resolves a world-space location, but the curve stores local
    coordinates — writing world coordinates straight in would fling the vertex
    off by the object's translation."""
    set_curve_point_world(dimension_curve, spline_index=0, point_index=1, world_co=Vector((13.0, 1.0, 5.0)))

    point = dimension_curve.data.splines[0].points[1]
    assert point.co[0] == pytest.approx(3.0)
    assert point.co[1] == pytest.approx(1.0)
    assert point.co[2] == pytest.approx(0.0)


def test_preserves_the_w_component_when_writing_a_point(dimension_curve):
    """POLY curve points are 4D; clobbering w with 0 collapses the point's
    weight and Blender stops drawing the segment."""
    set_curve_point_world(dimension_curve, spline_index=0, point_index=0, world_co=Vector((10.0, 2.0, 5.0)))

    assert dimension_curve.data.splines[0].points[0].co[3] == pytest.approx(1.0)


def test_flattens_an_off_plane_snap_onto_the_annotation_plane():
    """Snapping targets real model vertices, which sit at arbitrary depth. An
    annotation must stay on its drawing plane, so the snapped point is projected
    back onto it instead of dragging the vertex out of the drawing."""
    annotation_matrix = Matrix.Translation((0.0, 0.0, 2.0))

    flattened = project_point_to_annotation_plane(annotation_matrix, Vector((1.0, 3.0, 7.5)))

    assert flattened.x == pytest.approx(1.0)
    assert flattened.y == pytest.approx(3.0)
    assert flattened.z == pytest.approx(2.0)


def test_recognises_a_dimension_annotation(dimension_curve, link_ifc_entity):
    link_ifc_entity(dimension_curve, object_type="DIMENSION")

    assert is_dimension_annotation(dimension_curve) is True


def test_ignores_annotations_that_are_not_dimensions(dimension_curve, link_ifc_entity):
    """TEXT, SECTION_LEVEL and friends are curve annotations too — showing
    vertex handles on them would be meaningless."""
    link_ifc_entity(dimension_curve, object_type="TEXT")

    assert is_dimension_annotation(dimension_curve) is False


def test_ignores_non_curve_objects(mesh_object, link_ifc_entity):
    """The handles read ``data.splines``, which a mesh does not have."""
    link_ifc_entity(mesh_object, object_type="DIMENSION")

    assert is_dimension_annotation(mesh_object) is False


def test_ignores_objects_with_no_ifc_element(dimension_curve):
    """A plain Blender curve the user drew by hand is not an annotation."""
    assert is_dimension_annotation(dimension_curve) is False


def test_widget_shows_on_a_dimension_annotation_in_object_mode(dimension_curve, link_ifc_entity):
    link_ifc_entity(dimension_curve, object_type="DIMENSION")
    context = SimpleNamespace(mode="OBJECT", active_object=dimension_curve)

    assert GizmoDimensionVertexEdition.poll(context) is True


def test_widget_hides_in_edit_mode(dimension_curve, link_ifc_entity):
    """In edit mode Blender's own vertex tools apply; the handles would compete
    with them for clicks on the very same points."""
    link_ifc_entity(dimension_curve, object_type="DIMENSION")
    context = SimpleNamespace(mode="EDIT_CURVE", active_object=dimension_curve)

    assert GizmoDimensionVertexEdition.poll(context) is False


def test_both_classes_are_registered_with_the_drawing_module():
    """Unregistered gizmo classes simply never appear in the viewport, with no
    error to explain why."""
    import bonsai.bim.module.drawing as drawing_module

    assert GizmoDimensionVertex in drawing_module.classes
    assert GizmoDimensionVertexEdition in drawing_module.classes
    assert MoveDimensionVertex in drawing_module.classes


def test_the_classes_register_with_blender():
    """Being in the classes tuple is not enough — a bad bl_idname or property
    fails at registration, and gizmo classes never appear as bpy.types.<name>."""
    assert bpy.types.Gizmo.bl_rna_get_subclass_py("BIM_GT_gizmo_dimension_vertex") is GizmoDimensionVertex
    assert (
        bpy.types.GizmoGroup.bl_rna_get_subclass_py("OBJECT_GGT_bim_dimension_vertex_edition")
        is GizmoDimensionVertexEdition
    )
    assert bpy.types.Gizmo.bl_rna_get_subclass_py("BIM_GT_gizmo_dimension") is not None
    assert hasattr(bpy.ops.bim, "move_dimension_vertex")


def test_the_widget_is_drawn_while_the_operator_runs():
    """Without SHOW_MODAL_ALL Blender hides the group as soon as a modal
    operator starts, and the placement preview would never be seen."""
    assert "SHOW_MODAL_ALL" in GizmoDimensionVertexEdition.bl_options


def test_the_widget_feeds_the_preview_label_from_the_pending_move():
    """``BIM_GT_gizmo_dimension`` only calls its text_formatter when the owning
    group returns props, so the group has to answer get_props()."""
    assert GizmoDimensionVertexEdition.get_props(None, None) is get_pending_vertex_move()


def test_the_gizmo_only_launches_the_operator():
    """The handle is a launcher for the two-click operator, not a drag handle —
    a ``modal`` on the gizmo would swallow the clicks the operator needs."""
    assert not hasattr(GizmoDimensionVertex, "modal")
    assert MoveDimensionVertex.bl_idname == "bim.move_dimension_vertex"


def test_the_operator_takes_the_vertex_to_move_as_properties():
    """The launching gizmo can only pass data through operator properties, and
    the module's ``from __future__ import annotations`` is exactly what turns a
    property declaration into an inert string."""
    properties = {prop.identifier for prop in bpy.ops.bim.move_dimension_vertex.get_rna_type().properties}

    assert {"obj", "spline_index", "point_index"} <= properties


def test_anchors_the_axis_on_the_previous_point():
    assert neighbour_point_index(point_count=2, point_index=1) == 0


def test_anchors_the_first_point_on_the_next_one():
    """The first vertex has no previous point, so it measures against the
    second one instead."""
    assert neighbour_point_index(point_count=2, point_index=0) == 1


def test_reports_no_anchor_for_a_single_point_spline():
    assert neighbour_point_index(point_count=1, point_index=0) is None


def test_derives_the_slide_axis_from_the_two_vertices(dimension_curve):
    """ "Quota in linea": the moved vertex may only slide along the line the
    dimension already measures."""
    direction = dimension_axis_direction(dimension_curve, spline_index=0, point_index=1)

    assert direction.x == pytest.approx(1.0)
    assert direction.y == pytest.approx(0.0)


def test_falls_back_to_the_local_y_axis_when_the_vertices_coincide(dimension_curve):
    """A zero-length dimension gives no direction, but annotations are created
    along their own local Y, so that is the axis the user expects."""
    dimension_curve.matrix_world = Matrix.Rotation(radians(90), 4, "Z")
    dimension_curve.data.splines[0].points[1].co = (0.0, 0.0, 0.0, 1.0)

    direction = dimension_axis_direction(dimension_curve, spline_index=0, point_index=1)

    assert direction.x == pytest.approx(-1.0)
    assert direction.y == pytest.approx(0.0, abs=1e-6)
    assert direction.z == pytest.approx(0.0, abs=1e-6)


def test_snaps_the_polyline_plane_to_the_annotation_plane():
    """The polyline snap only knows the three world planes, so a plan drawing
    (annotation normal along Z) has to snap on XY."""
    assert annotation_plane_method(Matrix.Translation((0.0, 0.0, 3.0))) == "XY"


def test_snaps_a_section_drawing_on_the_plane_its_normal_faces():
    """Section and elevation drawings stand upright, so their annotations snap
    on a vertical plane instead."""
    assert annotation_plane_method(Matrix.Rotation(radians(90), 4, "X")) == "XZ"
    assert annotation_plane_method(Matrix.Rotation(radians(90), 4, "Y")) == "YZ"


def test_locks_the_snap_angle_to_the_dimension_axis():
    """``Snap.snap_on_axis`` measures the locked angle from a different pair of
    axes on each plane; getting the pair wrong silently rotates the lock."""
    assert axis_snap_angle("XY", Vector((0.0, 1.0, 0.0))) == pytest.approx(90.0)
    assert axis_snap_angle("XZ", Vector((0.0, 0.0, 1.0))) == pytest.approx(90.0)
    assert axis_snap_angle("YZ", Vector((0.0, 0.0, 1.0))) == pytest.approx(90.0)
    assert axis_snap_angle("XY", Vector((-1.0, 0.0, 0.0))) == pytest.approx(180.0)
    assert axis_snap_angle("YZ", Vector((0.0, -1.0, 0.0))) == pytest.approx(180.0)


def test_previews_the_pending_measurement_from_the_anchor():
    """The preview line is the dimension being edited: it runs from the anchor
    along the locked axis, and its length is the value the user is placing."""
    direction, length = preview_dimension(
        anchor_world=Vector((1.0, 0.0, 0.0)),
        location=Vector((4.0, 0.0, 0.0)),
        axis_direction=Vector((1.0, 0.0, 0.0)),
    )

    assert direction == Vector((1.0, 0.0, 0.0))
    assert length == pytest.approx(3.0)


def test_previews_a_vertex_dragged_past_its_anchor():
    """Sliding the vertex to the other side of the anchor flips the line rather
    than drawing it backwards through the anchor."""
    direction, length = preview_dimension(
        anchor_world=Vector((1.0, 0.0, 0.0)),
        location=Vector((-1.0, 0.0, 0.0)),
        axis_direction=Vector((1.0, 0.0, 0.0)),
    )

    assert direction == Vector((-1.0, 0.0, 0.0))
    assert length == pytest.approx(2.0)


def test_places_the_preview_gizmo_along_the_dimension():
    """``BIM_GT_gizmo_dimension`` draws along its local +X and offsets its text
    along local Y, so the matrix has to carry the drawing plane too."""
    matrix = preview_gizmo_matrix(
        location=Vector((5.0, 2.0, 0.0)),
        direction=Vector((0.0, 1.0, 0.0)),
        plane_normal=Vector((0.0, 0.0, 1.0)),
    )

    assert matrix.translation == Vector((5.0, 2.0, 0.0))
    assert matrix.col[0][:3] == pytest.approx((0.0, 1.0, 0.0))
    assert matrix.col[2][:3] == pytest.approx((0.0, 0.0, 1.0))


def test_the_widget_shows_the_preview_and_hides_the_handles_while_placing():
    """A GizmoGroup cannot be instantiated outside a 3D viewport, so the
    per-frame update is exercised on a stand-in."""
    lengths = []
    widget = SimpleNamespace(
        preview=SimpleNamespace(hide=True, matrix_basis=None, set_dimension_length=lengths.append),
        handles=[SimpleNamespace(hide=False)],
    )
    pending = get_pending_vertex_move()
    pending.start(
        anchor_world=Vector((1.0, 0.0, 0.0)),
        location=Vector((4.0, 0.0, 0.0)),
        axis_direction=Vector((1.0, 0.0, 0.0)),
        plane_normal=Vector((0.0, 0.0, 1.0)),
    )

    try:
        GizmoDimensionVertexEdition._update_preview(widget)

        assert widget.preview.hide is False
        assert widget.handles[0].hide is True
        assert lengths == [pytest.approx(3.0)]
        assert widget.preview.matrix_basis.translation == Vector((1.0, 0.0, 0.0))
    finally:
        pending.clear()

    GizmoDimensionVertexEdition._update_preview(widget)

    assert widget.preview.hide is True
    assert widget.handles[0].hide is False


def test_the_widget_hides_its_gizmos_during_a_blender_transform_modal(monkeypatch):
    """SHOW_MODAL_ALL keeps the group drawn during a G/R/S drag, but refresh()
    does not run then, so without this gate the handles hang frozen at their
    pre-drag positions while the annotation moves under them."""
    import bonsai.tool as tool

    monkeypatch.setattr(tool.Blender, "is_transform_modal_active", staticmethod(lambda context: True))

    widget = SimpleNamespace(
        preview=SimpleNamespace(hide=False, is_modal=False),
        handles=[SimpleNamespace(hide=False, is_modal=False)],
    )
    widget.gizmos = [widget.preview, *widget.handles]

    GizmoDimensionVertexEdition.draw_prepare(widget, SimpleNamespace())

    assert widget.handles[0].hide is True
    assert widget.preview.hide is True


def test_the_pending_move_starts_inactive():
    """A stale preview would linger over a drawing the user is no longer editing."""
    assert get_pending_vertex_move().is_active is False


def test_the_pending_move_is_published_and_cleared():
    pending = get_pending_vertex_move()

    pending.start(
        anchor_world=Vector((1.0, 0.0, 0.0)),
        location=Vector((3.0, 0.0, 0.0)),
        axis_direction=Vector((1.0, 0.0, 0.0)),
        plane_normal=Vector((0.0, 0.0, 1.0)),
    )
    try:
        assert pending.is_active is True
        assert pending.anchor_world == Vector((1.0, 0.0, 0.0))
        assert pending.location == Vector((3.0, 0.0, 0.0))
    finally:
        pending.clear()

    assert pending.is_active is False


def test_formats_the_live_value_like_the_drawing_label(monkeypatch, meters_length_unit):
    """The readout and the dimension text must never disagree, so both read
    precision and decimal places from the active drawing's pset."""
    from bonsai.bim.module.drawing.data import DrawingsData

    monkeypatch.setattr(DrawingsData, "data", {"active_drawing_pset_data": {"DecimalPlaces": 1}})

    assert format_dimension_value(1.4321) == "1.4"


def test_formats_the_live_value_without_an_active_drawing(monkeypatch, meters_length_unit):
    """Drawing data is not loaded until a drawing is activated; the readout
    still has to show something."""
    from bonsai.bim.module.drawing.data import DrawingsData

    monkeypatch.setattr(DrawingsData, "data", {})

    assert format_dimension_value(1.4321) == "1.432"
