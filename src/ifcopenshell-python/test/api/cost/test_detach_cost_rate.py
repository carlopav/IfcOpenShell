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
import ifcopenshell.api.unit
import ifcopenshell.util.cost
import test.bootstrap


class TestDetachCostRate(test.bootstrap.IFC4):
    def create_rate(self, applied_value=5.0, with_unit_basis=False):
        sor = ifcopenshell.api.cost.add_cost_schedule(
            self.file, name="SOR", predefined_type="SCHEDULEOFRATES"
        )
        rate = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=sor)
        value = ifcopenshell.api.cost.add_cost_value(self.file, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=value, attributes={"AppliedValue": applied_value}
        )
        if with_unit_basis:
            unit = ifcopenshell.api.unit.add_si_unit(self.file, unit_type="AREAUNIT")
            ifcopenshell.api.cost.edit_cost_value(
                self.file,
                cost_value=value,
                attributes={"UnitBasis": {"ValueComponent": 1.0, "UnitComponent": unit}},
            )
        return rate, value

    def add_dependent(self, rate, name="BoQ"):
        schedule = ifcopenshell.api.cost.add_cost_schedule(self.file, name=name, predefined_type="BUDGET")
        item = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        ifcopenshell.api.cost.assign_cost_value(self.file, cost_item=item, cost_rate=rate)
        ifcopenshell.api.control.assign_control(self.file, relating_control=rate, related_objects=[item])
        return item

    def test_dependent_gets_its_own_private_copy_of_the_values(self):
        rate, value = self.create_rate()
        item = self.add_dependent(rate)
        assert item.CostValues == (value,)  # shared before detach

        mapping = ifcopenshell.api.cost.detach_cost_rate(self.file, cost_item=item)

        assert item.CostValues and item.CostValues[0] != value
        assert item.CostValues[0] == mapping[value]
        # Same monetary value, but an independent IfcCostValue entity.
        assert item.CostValues[0].AppliedValue.wrappedValue == 5.0
        assert rate.CostValues == (value,)  # the rate is untouched

    def test_removes_the_link_to_the_rate(self):
        rate, _ = self.create_rate()
        item = self.add_dependent(rate)
        ifcopenshell.api.cost.detach_cost_rate(self.file, cost_item=item)
        assert ifcopenshell.util.cost.get_rate_dependent_cost_items(rate) == []
        # The rate link is gone, but the item still belongs to its own schedule.
        assert ifcopenshell.util.cost.get_cost_schedule(item) is not None

    def test_other_dependents_are_unaffected(self):
        rate, value = self.create_rate()
        item1 = self.add_dependent(rate, name="BoQ A")
        item2 = self.add_dependent(rate, name="BoQ B")
        ifcopenshell.api.cost.detach_cost_rate(self.file, cost_item=item1)
        assert item2.CostValues == (value,)
        assert ifcopenshell.util.cost.get_rate_dependent_cost_items(rate) == [item2]

    def test_editing_the_detached_value_does_not_affect_the_rate(self):
        rate, value = self.create_rate(applied_value=5.0)
        item = self.add_dependent(rate)
        ifcopenshell.api.cost.detach_cost_rate(self.file, cost_item=item)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=item.CostValues[0], attributes={"AppliedValue": 99.0}
        )
        assert item.CostValues[0].AppliedValue.wrappedValue == 99.0
        assert value.AppliedValue.wrappedValue == 5.0  # rate is unchanged

    def test_shared_units_are_not_duplicated(self):
        rate, value = self.create_rate(with_unit_basis=True)
        item = self.add_dependent(rate)
        units_before = self.file.by_type("IfcNamedUnit")
        ifcopenshell.api.cost.detach_cost_rate(self.file, cost_item=item)
        assert self.file.by_type("IfcNamedUnit") == units_before  # no new units
        # The copied value has its own UnitBasis but references the same unit.
        assert item.CostValues[0].UnitBasis != value.UnitBasis
        assert item.CostValues[0].UnitBasis.UnitComponent == value.UnitBasis.UnitComponent


class TestDetachCostRateIFC4X3(test.bootstrap.IFC4X3, TestDetachCostRate):
    pass
