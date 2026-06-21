# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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


import ifcopenshell
import ifcopenshell.api.control
import ifcopenshell.api.cost

import bonsai.core.tool
import bonsai.tool as tool
import test.bim.bootstrap
from bonsai.tool.cost import Cost as subject
from test.bim.bootstrap import NewFile


def create_rate_with_dependents(ifc):
    """Build a schedule of rates with one rate borrowed by two cost items in
    two separate cost schedules, mirroring Bonsai's assign_cost_value flow."""
    sor = ifcopenshell.api.cost.add_cost_schedule(ifc, name="SOR", predefined_type="SCHEDULEOFRATES")
    rate = ifcopenshell.api.cost.add_cost_item(ifc, cost_schedule=sor)
    value = ifcopenshell.api.cost.add_cost_value(ifc, parent=rate)
    ifcopenshell.api.cost.edit_cost_value(ifc, cost_value=value, attributes={"AppliedValue": 5.0})
    dependents = []
    for i in range(2):
        schedule = ifcopenshell.api.cost.add_cost_schedule(ifc, name=f"BoQ{i}", predefined_type="BUDGET")
        item = ifcopenshell.api.cost.add_cost_item(ifc, cost_schedule=schedule)
        ifcopenshell.api.cost.assign_cost_value(ifc, cost_item=item, cost_rate=rate)
        ifcopenshell.api.control.assign_control(ifc, relating_control=rate, related_objects=[item])
        dependents.append(item)
    return sor, rate, value, dependents


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Cost)


class TestDisableEditingCostItemParent(NewFile):
    def test_avoid_recursion_error(newfile, monkeypatch):
        class DummyProps:
            def __init__(self):
                self.change_cost_item_parent = None
                self.active_cost_item_id = 5

        props = DummyProps()
        monkeypatch.setattr("bonsai.tool.Cost.get_cost_props", lambda: props)
        subject.disable_editing_cost_item_parent()
        assert props.active_cost_item_id == 0
        assert props.change_cost_item_parent is not False


class TestGetRateDependentCostItems(NewFile):
    def test_returns_the_cost_items_controlled_by_a_rate(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        _, rate, _, dependents = create_rate_with_dependents(ifc)
        assert set(subject.get_rate_dependent_cost_items(rate)) == set(dependents)

    def test_returns_empty_for_a_plain_cost_item(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        schedule = ifcopenshell.api.cost.add_cost_schedule(ifc, name="BoQ", predefined_type="BUDGET")
        item = ifcopenshell.api.cost.add_cost_item(ifc, cost_schedule=schedule)
        assert subject.get_rate_dependent_cost_items(item) == []


class TestGetControlledCostItemsInSubtree(NewFile):
    def test_detects_dependents_controlled_by_the_item(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        _, rate, _, dependents = create_rate_with_dependents(ifc)
        assert set(subject.get_controlled_cost_items_in_subtree(rate)) == set(dependents)

    def test_detects_dependents_controlled_by_a_descendant(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        sor = ifcopenshell.api.cost.add_cost_schedule(ifc, name="SOR", predefined_type="SCHEDULEOFRATES")
        summary = ifcopenshell.api.cost.add_cost_item(ifc, cost_schedule=sor)
        rate = ifcopenshell.api.cost.add_cost_item(ifc, cost_item=summary)
        value = ifcopenshell.api.cost.add_cost_value(ifc, parent=rate)
        boq = ifcopenshell.api.cost.add_cost_schedule(ifc, name="BoQ", predefined_type="BUDGET")
        item = ifcopenshell.api.cost.add_cost_item(ifc, cost_schedule=boq)
        ifcopenshell.api.cost.assign_cost_value(ifc, cost_item=item, cost_rate=rate)
        ifcopenshell.api.control.assign_control(ifc, relating_control=rate, related_objects=[item])
        assert subject.get_controlled_cost_items_in_subtree(summary) == [item]


class TestGroupCostItemsBySchedule(NewFile):
    def test_groups_dependents_by_their_schedule_name(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        _, _, _, dependents = create_rate_with_dependents(ifc)
        assert subject.group_cost_items_by_schedule(dependents) == [("BoQ0", 1), ("BoQ1", 1)]
