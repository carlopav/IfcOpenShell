# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

import ifcopenshell
import ifcopenshell.api.control
import ifcopenshell.util.element

# Units are shared globally, so they must not be duplicated when copying values.
EXCLUDED_UNIT_CLASSES = ("IfcNamedUnit", "IfcDerivedUnit", "IfcMonetaryUnit")


def detach_cost_rate(
    file: ifcopenshell.file, cost_item: ifcopenshell.entity_instance
) -> dict[ifcopenshell.entity_instance, ifcopenshell.entity_instance]:
    """Detaches a cost item from the rate it borrows its values from

    A cost item may borrow its values from a cost item in a schedule of rates
    via :func:`ifcopenshell.api.cost.assign_cost_value`, which shares the rate's
    ``IfcCostValue`` entities and links the two with an
    ``IfcRelAssignsToControl``. Because the entities are shared, editing the
    dependent's values would mutate the rate (and every sibling) too, and any
    rewrite would silently diverge from the rate while the link still claims
    otherwise.

    This usecase severs that link: the cost item receives its own private deep
    copy of its current cost values (shared units are preserved, not
    duplicated) and the ``IfcRelAssignsToControl`` to the rate is removed. The
    cost item becomes an ordinary, independent cost item whose values can be
    edited locally without affecting the rate.

    :param cost_item: The dependent IfcCostItem to detach from its rate.
    :return: A mapping of each original (shared) ``IfcCostValue`` to its new
        private copy, so callers can retarget an edit that referenced the old
        shared value. Empty if the cost item had no cost values.

    Example:

    .. code:: python

        # item borrows its values from rate
        ifcopenshell.api.cost.assign_cost_value(model, cost_item=item, cost_rate=rate)
        ifcopenshell.api.control.assign_control(model, relating_control=rate, related_objects=[item])

        # detach so item can be priced independently
        ifcopenshell.api.cost.detach_cost_rate(model, cost_item=item)
    """
    rate = None
    for rel in cost_item.HasAssignments or []:
        if rel.is_a("IfcRelAssignsToControl") and rel.RelatingControl and rel.RelatingControl.is_a("IfcCostItem"):
            rate = rel.RelatingControl
            break

    mapping: dict[ifcopenshell.entity_instance, ifcopenshell.entity_instance] = {}
    if cost_item.CostValues:
        new_values = []
        for cost_value in cost_item.CostValues:
            new_value = ifcopenshell.util.element.copy_deep(file, cost_value, exclude=EXCLUDED_UNIT_CLASSES)
            mapping[cost_value] = new_value
            new_values.append(new_value)
        cost_item.CostValues = new_values

    if rate:
        ifcopenshell.api.control.unassign_control(file, relating_control=rate, related_objects=[cost_item])

    return mapping
