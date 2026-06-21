# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2024 Dion Moult <dion@thinkmoult.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

import ifcopenshell.api.control
import ifcopenshell.api.cost
import test.bootstrap


class TestRemoveCostItem(test.bootstrap.IFC4):
    def test_remove_a_cost_item(self):
        schedule = ifcopenshell.api.cost.add_cost_schedule(self.file, name="Foo", predefined_type="BUDGET")
        item1 = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=item1)
        assert not self.file.by_type("IfcCostItem")
        assert not self.file.by_type("IfcRelAssignsToControl")

    def test_remove_a_sub_cost_item(self):
        schedule = ifcopenshell.api.cost.add_cost_schedule(self.file, name="Foo", predefined_type="BUDGET")
        item1 = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        item2 = ifcopenshell.api.cost.add_cost_item(self.file, cost_item=item1)
        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=item2)
        assert self.file.by_type("IfcCostItem") == [item1]
        assert self.file.by_type("IfcRelAssignsToControl")
        assert not self.file.by_type("IfcRelNests")

    def test_remove_a_parent_cost_item(self):
        schedule = ifcopenshell.api.cost.add_cost_schedule(self.file, name="Foo", predefined_type="BUDGET")
        item1 = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        item2 = ifcopenshell.api.cost.add_cost_item(self.file, cost_item=item1)
        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=item1)
        assert not self.file.by_type("IfcCostItem")
        assert not self.file.by_type("IfcRelAssignsToControl")
        assert not self.file.by_type("IfcRelNests")

    def test_remove_cost_item_keep_rel_for_other_cost_items(self):
        schedule = ifcopenshell.api.cost.add_cost_schedule(self.file, name="Foo", predefined_type="BUDGET")
        item1 = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        item2 = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=item1)
        assert self.file.by_type("IfcCostItem") == [item2]
        rel = next(iter(self.file.by_type("IfcRelAssignsToControl")), None)
        assert rel
        assert rel.RelatedObjects == (item2,)


class TestRemoveCostItemIFC2X3(test.bootstrap.IFC2X3, TestRemoveCostItem):
    pass


class TestRemoveCostRateCostItem(test.bootstrap.IFC4):
    """Deleting a cost item used as a rate by other cost items."""

    def add_dependents(self, rate, count=2):
        dependents = []
        for i in range(count):
            schedule = ifcopenshell.api.cost.add_cost_schedule(
                self.file, name=f"BoQ{i}", predefined_type="BUDGET"
            )
            item = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
            ifcopenshell.api.cost.assign_cost_value(self.file, cost_item=item, cost_rate=rate)
            ifcopenshell.api.control.assign_control(
                self.file, relating_control=rate, related_objects=[item]
            )
            dependents.append(item)
        return dependents

    def create_rate_with_dependents(self):
        sor = ifcopenshell.api.cost.add_cost_schedule(
            self.file, name="SOR", predefined_type="SCHEDULEOFRATES"
        )
        rate = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=sor)
        value = ifcopenshell.api.cost.add_cost_value(self.file, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=value, attributes={"AppliedValue": 5.0}
        )
        return rate, value, self.add_dependents(rate)

    def test_removing_a_rate_detaches_its_dependents(self):
        rate, value, dependents = self.create_rate_with_dependents()
        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=rate)
        assert rate not in self.file.by_type("IfcCostItem")
        for item in dependents:
            assert item in self.file.by_type("IfcCostItem")
            # Each dependent keeps its own private copy of the value.
            assert item.CostValues and item.CostValues[0] != value
            assert item.CostValues[0].AppliedValue.wrappedValue == 5.0
        # No dangling rate link remains.
        for rel in self.file.by_type("IfcRelAssignsToControl"):
            assert rel.RelatingControl is not None
            assert rel.RelatingControl != rate

    def test_detached_dependents_are_independent_of_each_other(self):
        rate, value, dependents = self.create_rate_with_dependents()
        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=rate)
        # Editing one former dependent must not affect the others.
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=dependents[0].CostValues[0], attributes={"AppliedValue": 99.0}
        )
        assert dependents[0].CostValues[0].AppliedValue.wrappedValue == 99.0
        assert dependents[1].CostValues[0].AppliedValue.wrappedValue == 5.0

    def test_removing_a_parent_of_a_rate_detaches_its_dependents(self):
        # The controller is a descendant of the deleted item, exercising the
        # recursive deletion path.
        sor = ifcopenshell.api.cost.add_cost_schedule(
            self.file, name="SOR", predefined_type="SCHEDULEOFRATES"
        )
        summary = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=sor)
        rate = ifcopenshell.api.cost.add_cost_item(self.file, cost_item=summary)
        value = ifcopenshell.api.cost.add_cost_value(self.file, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=value, attributes={"AppliedValue": 5.0}
        )
        dependents = self.add_dependents(rate)

        ifcopenshell.api.cost.remove_cost_item(self.file, cost_item=summary)
        assert summary not in self.file.by_type("IfcCostItem")
        assert rate not in self.file.by_type("IfcCostItem")
        for item in dependents:
            assert item in self.file.by_type("IfcCostItem")
            assert item.CostValues and item.CostValues[0].AppliedValue.wrappedValue == 5.0


class TestRemoveCostRateCostItemIFC4X3(test.bootstrap.IFC4X3, TestRemoveCostRateCostItem):
    pass
