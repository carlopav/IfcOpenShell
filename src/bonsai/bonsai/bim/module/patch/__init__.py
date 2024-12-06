# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>
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

import bpy
from . import ui, prop, operator

classes = (
    operator.ExecuteIfcPatch,
    operator.ExtractSelectedElements,
    operator.RunMigratePatch,
    operator.SelectIfcPatchInput,
    operator.SelectIfcPatchOutput,
    operator.UpdateIfcPatchArguments,
    prop.BIMPatchProperties,
    ui.BIM_PT_patch,
)


def register():
    bpy.types.Scene.BIMPatchProperties = bpy.props.PointerProperty(type=prop.BIMPatchProperties)


def unregister():
    del bpy.types.Scene.BIMPatchProperties
