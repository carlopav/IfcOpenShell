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
import ifcopenshell.api.cost
import ifcopenshell.util.cost


def sync_cost_rate(
    file: ifcopenshell.file,
    cost_rate: ifcopenshell.entity_instance,
    sync_values: bool = True,
    sync_name: bool = True,
    sync_description: bool = True,
    sync_identification: bool = False,
) -> list[ifcopenshell.entity_instance]:
    """Brings a cost rate's dependents back in sync with the rate

    A cost item may borrow its cost values from a cost item in a schedule of
    rates via :func:`ifcopenshell.api.cost.assign_cost_value`, which shares the
    rate's ``IfcCostValue`` entities and creates an ``IfcRelAssignsToControl``
    link. Editing the rate's value *in place* propagates for free because the
    entities are shared, but any flow that *replaces* the rate's ``CostValues``
    (e.g. removing then re-adding a value) silently breaks the share, leaving
    the dependents pointing at stale entities. The rate's ``Name`` and
    ``Description`` are per-item attributes and never propagate on their own.

    This usecase treats the rate as the master and reconciles every dependent
    cost item (``cost_rate.Controls`` → ``RelatedObjects``):

    - When ``sync_values`` is enabled, the rate's *current* ``CostValues`` are
      re-shared onto each dependent, restoring the link after any rewrite. This
      is idempotent for dependents that are already in sync.
    - When ``sync_name`` / ``sync_description`` are enabled, those attributes
      are copied from the rate onto each dependent.
    - ``Identification`` is **not** copied unless ``sync_identification`` is
      enabled, since it is legitimate for a dependent to keep its own project
      hierarchy coding.

    The data mechanism is identical to Bonsai's existing approach (shared
    ``IfcCostValue`` entities); no copies are introduced.

    :param cost_rate: The IfcCostItem acting as a rate (typically in a
        ``SCHEDULEOFRATES`` cost schedule).
    :param sync_values: Re-share the rate's cost values onto the dependents.
    :param sync_name: Copy the rate's ``Name`` onto the dependents.
    :param sync_description: Copy the rate's ``Description`` onto the dependents.
    :param sync_identification: Copy the rate's ``Identification`` onto the
        dependents. Off by default.
    :return: The list of dependent IfcCostItem that were synchronised.

    Example:

    .. code:: python

        # A schedule of rates with a single rate of 5.0
        sor = ifcopenshell.api.cost.add_cost_schedule(model, predefined_type="SCHEDULEOFRATES")
        rate = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=sor)
        value = ifcopenshell.api.cost.add_cost_value(model, parent=rate)
        ifcopenshell.api.cost.edit_cost_value(model, cost_value=value, attributes={"AppliedValue": 5.0})

        # A bill of quantities borrowing the rate
        boq = ifcopenshell.api.cost.add_cost_schedule(model)
        item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=boq)
        ifcopenshell.api.cost.assign_cost_value(model, cost_item=item, cost_rate=rate)
        ifcopenshell.api.control.assign_control(model, relating_control=rate, related_objects=[item])

        # The rate is edited in a way that rewrites its values; bring dependents back in sync
        ifcopenshell.api.cost.edit_cost_item(model, cost_item=rate, attributes={"Name": "Concrete C30"})
        ifcopenshell.api.cost.sync_cost_rate(model, cost_rate=rate)
    """
    dependents = ifcopenshell.util.cost.get_rate_dependent_cost_items(cost_rate)
    for dependent in dependents:
        if sync_values:
            # Re-share the rate's current cost value entities. assign_cost_value
            # is share-aware when clearing the dependent's stale values.
            ifcopenshell.api.cost.assign_cost_value(file, cost_item=dependent, cost_rate=cost_rate)
        attributes = {}
        if sync_name:
            attributes["Name"] = cost_rate.Name
        if sync_description:
            attributes["Description"] = cost_rate.Description
        if sync_identification:
            attributes["Identification"] = cost_rate.Identification
        if attributes:
            ifcopenshell.api.cost.edit_cost_item(file, cost_item=dependent, attributes=attributes)
    return dependents
