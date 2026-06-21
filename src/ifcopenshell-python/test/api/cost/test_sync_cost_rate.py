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


class TestSyncCostRate(test.bootstrap.IFC4):
    def create_rate(self, applied_value=5.0):
        sor = ifcopenshell.api.cost.add_cost_schedule(
            self.file, name="SOR", predefined_type="SCHEDULEOFRATES"
        )
        rate = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=sor)
        value = ifcopenshell.api.cost.add_cost_value(self.file, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=value, attributes={"AppliedValue": applied_value}
        )
        ifcopenshell.api.cost.edit_cost_item(
            self.file,
            cost_item=rate,
            attributes={"Name": "Concrete", "Description": "C30/37", "Identification": "R1"},
        )
        return rate, value

    def add_dependent(self, rate, schedule_name, identification):
        schedule = ifcopenshell.api.cost.add_cost_schedule(
            self.file, name=schedule_name, predefined_type="BUDGET"
        )
        item = ifcopenshell.api.cost.add_cost_item(self.file, cost_schedule=schedule)
        ifcopenshell.api.cost.assign_cost_value(self.file, cost_item=item, cost_rate=rate)
        # Mirror Bonsai's navigable rate link.
        ifcopenshell.api.control.assign_control(self.file, relating_control=rate, related_objects=[item])
        ifcopenshell.api.cost.edit_cost_item(
            self.file, cost_item=item, attributes={"Identification": identification}
        )
        return item

    def test_returns_the_dependents_grouped_by_relationship(self):
        rate, _ = self.create_rate()
        item1 = self.add_dependent(rate, "BoQ A", "A1")
        item2 = self.add_dependent(rate, "BoQ B", "B1")
        dependents = ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate)
        assert set(dependents) == {item1, item2}

    def test_no_dependents_is_a_noop(self):
        rate, _ = self.create_rate()
        assert ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate) == []

    def test_dependents_share_the_rate_values_after_assignment(self):
        rate, value = self.create_rate()
        item = self.add_dependent(rate, "BoQ A", "A1")
        assert item.CostValues == (value,)

    def test_re_shares_values_after_a_rewrite_breaks_the_share(self):
        rate, value = self.create_rate(applied_value=5.0)
        item1 = self.add_dependent(rate, "BoQ A", "A1")
        item2 = self.add_dependent(rate, "BoQ B", "B1")

        # Rewrite the rate's values: remove the shared value (kept because the
        # dependents still reference it) then add a fresh one.
        ifcopenshell.api.cost.remove_cost_value(self.file, parent=rate, cost_value=value)
        new_value = ifcopenshell.api.cost.add_cost_value(self.file, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=new_value, attributes={"AppliedValue": 9.0}
        )

        # The dependents are now stale: they still point at the old value.
        assert item1.CostValues == (value,)
        assert item2.CostValues == (value,)
        assert rate.CostValues == (new_value,)

        ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate)

        assert item1.CostValues == (new_value,)
        assert item2.CostValues == (new_value,)

    def test_propagates_name_and_description_by_default(self):
        rate, _ = self.create_rate()
        item = self.add_dependent(rate, "BoQ A", "A1")
        ifcopenshell.api.cost.edit_cost_item(
            self.file, cost_item=rate, attributes={"Name": "Steel", "Description": "S355"}
        )
        ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate)
        assert item.Name == "Steel"
        assert item.Description == "S355"

    def test_does_not_propagate_identification_by_default(self):
        rate, _ = self.create_rate()
        item = self.add_dependent(rate, "BoQ A", "A1")
        ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate)
        assert item.Identification == "A1"
        assert rate.Identification == "R1"

    def test_propagates_identification_when_requested(self):
        rate, _ = self.create_rate()
        item = self.add_dependent(rate, "BoQ A", "A1")
        ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate, sync_identification=True)
        assert item.Identification == "R1"

    def test_can_sync_values_only(self):
        rate, value = self.create_rate()
        item = self.add_dependent(rate, "BoQ A", "A1")
        # Establish a synced name first.
        ifcopenshell.api.cost.sync_cost_rate(self.file, cost_rate=rate)
        assert item.Name == "Concrete"
        # Rewrite the rate (new name + new value entity), then sync values only.
        ifcopenshell.api.cost.edit_cost_item(self.file, cost_item=rate, attributes={"Name": "Steel"})
        ifcopenshell.api.cost.remove_cost_value(self.file, parent=rate, cost_value=value)
        new_value = ifcopenshell.api.cost.add_cost_value(self.file, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(
            self.file, cost_value=new_value, attributes={"AppliedValue": 9.0}
        )
        ifcopenshell.api.cost.sync_cost_rate(
            self.file, cost_rate=rate, sync_name=False, sync_description=False
        )
        assert item.Name == "Concrete"  # name was not re-synced
        assert item.CostValues == (new_value,)  # values were re-shared


class TestSyncCostRateIFC4X3(test.bootstrap.IFC4X3, TestSyncCostRate):
    pass
