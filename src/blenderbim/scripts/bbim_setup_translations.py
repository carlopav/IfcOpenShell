import bpy
import addon_utils
import shutil
import tempfile
import importlib
import os
import bl_i18n_utils
from pathlib import Path

bl_info = {
    "name": "BlenderBIM Translations",
    "description": "",
    "author": "IfcOpenShell Contributors",
    "blender": (2, 80, 0),
    "version": (0, 0, 999999),
    "location": "Properties -> Render -> BBIM Update Translation",
    "tracker_url": "https://github.com/IfcOpenShell/IfcOpenShell/issues",
    "category": "System",
}

context = bpy.context
SUPPORT_LANGUAGES = ["ru_RU", "de_DE"]
ADDON_NAME = "localization_test"
BRANCHES_DIR = Path(context.preferences.filepaths.i18n_branches_directory)


def is_addon_loaded(addon_name) -> bool:
    loaded_default, loaded_state = addon_utils.check(addon_name)
    return loaded_state


def dump_py_messages_monkey_patch(msgs, reports, addons, settings, addons_only=False):
    ignore_addon_dirs = ["libs"]

    def _get_files(path, ignore_dirs=tuple()):
        if not os.path.exists(path):
            return []
        if os.path.isdir(path):
            files = []
            for dpath, subdirs, fnames in os.walk(path, topdown=True, followlinks=True):
                if Path(dpath) in ignore_dirs:
                    subdirs.clear()  # skip walking through `subdirs`
                    continue

                for fn in fnames:
                    if not fn.endswith(".py"):
                        continue
                    if fn.startswith("_") and fn != "__init__.py":
                        continue
                    files.append(os.path.join(dpath, fn))

            return files

        return [path]

    files = []
    if not addons_only:
        for path in settings.CUSTOM_PY_UI_FILES:
            for root in (bpy.utils.resource_path(t) for t in ("USER", "LOCAL", "SYSTEM")):
                files += _get_files(os.path.join(root, path))

    # Add all given addons.
    for mod in addons:
        fn = mod.__file__
        if os.path.basename(fn) == "__init__.py":
            parent_dir = Path(fn).parent
            ignore_dirs = [parent_dir / dpath for dpath in ignore_addon_dirs]
            files += _get_files(os.path.dirname(fn), ignore_dirs=ignore_dirs)
        else:
            files.append(fn)

    bl_i18n_utils.bl_extract_messages.dump_py_messages_from_files(msgs, reports, sorted(files), settings)


def dump_addon_messages(module_name, do_checks, settings):
    import datetime
    import addon_utils
    import bl_i18n_utils.utils as utils
    from bl_i18n_utils.bl_extract_messages import (
        _gen_reports,
        _gen_check_ctxt,
        dump_rna_messages,
        _diff_check_ctxt,
        dump_py_messages,
        dump_addon_bl_info,
        print_info,
    )

    # Enable our addon.
    ver = module_name
    rev = 0
    date = datetime.datetime.now()
    pot = utils.I18nMessages.gen_empty_messages(
        settings.PARSER_TEMPLATE_ID, ver, rev, date, date.year, settings=settings
    )
    msgs = pot.msgs

    minus_pot = utils.I18nMessages.gen_empty_messages(
        settings.PARSER_TEMPLATE_ID, ver, rev, date, date.year, settings=settings
    )
    minus_msgs = minus_pot.msgs

    check_ctxt = _gen_check_ctxt(settings) if do_checks else None
    minus_check_ctxt = _gen_check_ctxt(settings) if do_checks else None

    # Get strings from RNA, our addon being disabled
    print("D")
    reports = _gen_reports(check_ctxt)
    print("E")
    dump_rna_messages(minus_msgs, reports, settings)
    print("F")

    # Now enable our addon, and re-scan RNA.
    addon = utils.enable_addons(addons={module_name})[0]
    print("A")
    reports["check_ctxt"] = minus_check_ctxt
    print("B")
    dump_rna_messages(msgs, reports, settings)
    print("C")

    # and make the diff!
    for key in minus_msgs:
        if key != settings.PO_HEADER_KEY:
            if key in msgs:
                del msgs[key]
            else:
                # This should not happen, but some messages seem to have
                # leaked on add-on unregister and register?
                print(f"Key not found in msgs: {key}")

    if check_ctxt:
        _diff_check_ctxt(check_ctxt, minus_check_ctxt)

    # and we are done with those!
    del minus_pot
    del minus_msgs
    del minus_check_ctxt

    # get strings from UI layout definitions text="..." args
    reports["check_ctxt"] = check_ctxt
    dump_py_messages(msgs, reports, {addon}, settings, addons_only=True)

    # Get strings from the addon's bl_info
    dump_addon_bl_info(msgs, reports, addon, settings)

    pot.unescape()  # Strings gathered in py/C source code may contain escaped chars...
    print_info(reports, pot)

    print("Finished extracting UI messages!")

    return pot


class SetupTranslationUI(bpy.types.Operator):
    bl_idname = "bim.setup_translation_ui"
    bl_label = "Setup Translation UI"
    bl_options = set()

    def execute(self, context):
        if not is_addon_loaded("ui_translate"):
            raise Exception('"Manage UI translations" addon is not enabled')

        from ui_translate.settings import settings as ui_translate_settings

        i18n_settings = context.window_manager.i18n_update_settings
        if not i18n_settings.is_init:
            raise Exception(
                "UI Translation settings are not initalized. Make sure the following directories exist:\n"
                f" - {ui_translate_settings.WORK_DIR}\n"
                f" - {ui_translate_settings.BLENDER_I18N_PO_DIR}\n"
            )

        # we monkey patch `bl_i18n_utils.bl_extract_messages.dump_py_messages`
        # as it's doesn't support ignoring folders
        # and we need it, otherwise translation addon will try to parse strings
        # from all BlenderBIM dependencies :O
        bl_i18n_utils.bl_extract_messages.dump_py_messages = dump_py_messages_monkey_patch
        bl_i18n_utils.bl_extract_messages.dump_addon_messages = dump_addon_messages

        # setup selected languages
        for lang in i18n_settings.langs:
            lang.use = lang.uid in SUPPORT_LANGUAGES

        context.scene.translation_ui_is_loaded = True

        return {"FINISHED"}


class ReloadPyTranslations(bpy.types.Operator):
    bl_idname = "bim.reload_py_translations"
    bl_label = "Reload Py Translations"
    bl_description = "Parse strings from Blender objects of the addon to `translations.py`"
    bl_options = set()

    def execute(self, context):
        if is_addon_loaded(ADDON_NAME):
            # ref: https://projects.blender.org/blender/blender/issues/116579
            raise Exception(
                f"'{ADDON_NAME}' addon is enabled.\n"
                "Need to disable it, restart Blender and start reloading translations again.\n"
                "Otherwise some strings to translate might get lost due Blender bug."
            )

        bpy.ops.ui.i18n_addon_translation_update("INVOKE_DEFAULT", module_name=ADDON_NAME)
        self.report({"INFO"}, "Translations py data is saved.")
        return {"FINISHED"}


class ConvertTranslationsToPo(bpy.types.Operator):
    bl_idname = "bim.convert_translations_to_po"
    bl_label = "Convert Translations To .po"
    bl_description = (
        "Extract current translation strings from translation.py to .po files and saves them to I18n Branches directory"
    )
    bl_options = set()

    def execute(self, context):
        temp_po_dir = tempfile.TemporaryDirectory()

        if not BRANCHES_DIR.is_dir():
            raise Exception(f"I18n Branches directory doesn't exist: {BRANCHES_DIR.as_posix()}")

        bpy.ops.ui.i18n_addon_translation_export(
            module_name=ADDON_NAME, directory=temp_po_dir.name, use_export_pot=False
        )

        # NOTE: we use I18n branches directory
        # because it is the directory that later will be used to edit translation from UI.
        # I18n directory also has a bit different format then `ui_translate.export/import`,
        # every .po file has a parent folder with the same name
        # so we rearrange the exported data that way
        for file in Path(temp_po_dir.name).iterdir():
            branches_subdir = BRANCHES_DIR / file.stem
            branches_subdir.mkdir(exist_ok=True)
            file.replace(branches_subdir / file.name)

        temp_po_dir.cleanup()
        self.report({"INFO"}, f"Translations .po files are saved to {BRANCHES_DIR}.")
        return {"FINISHED"}


class UpdateTranslationsFromPo(bpy.types.Operator):
    bl_idname = "bim.update_translations_from_po"
    bl_label = "Update Translations From .po"
    bl_description = (
        "Load translation strings from po files at I18n Branches\n"
        "back to translations.py (they also get copied to `locale` directory of the addon)"
    )
    bl_options = set()

    def execute(self, context):
        temp_po_dir = tempfile.TemporaryDirectory()
        temp_po_dir_path = Path(temp_po_dir.name)
        for file in BRANCHES_DIR.glob("**/*"):
            if file.suffix != ".po":
                continue
            shutil.copy(file, temp_po_dir_path / file.name)

        bpy.ops.ui.i18n_addon_translation_import(
            module_name=ADDON_NAME,
            directory=temp_po_dir.name,
        )

        temp_po_dir.cleanup()

        # update translations in current Blender session
        bpy.app.translations.unregister(ADDON_NAME)
        addon_module = importlib.import_module(ADDON_NAME)
        translations_module = getattr(addon_module, "translations")
        importlib.reload(translations_module)
        bpy.app.translations.register(ADDON_NAME, translations_module.translations_dict)
        self.report({"INFO"}, f"Addon's translation updated from .po in {BRANCHES_DIR}")
        return {"FINISHED"}


class DisableEnableAddon(bpy.types.Operator):
    bl_idname = "bim.disable_enable_addon"
    bl_label = "Disable/Enable addon"
    bl_description = "Will enable addon if it's disabled, will disable it and restart Blender otherwise"
    bl_options = set()

    def execute(self, context):
        if not is_addon_loaded(ADDON_NAME):
            addon_utils.enable("blenderbim", default_set=True)
            return {"FINISHED"}

        import os
        import subprocess

        addon_utils.disable("blenderbim", default_set=True)

        blender_exe = bpy.app.binary_path
        head, tail = os.path.split(blender_exe)
        blender_launcher = os.path.join(head, "blender-launcher.exe")
        subprocess.run([blender_launcher, "-con", "--python-expr", "import bpy; bpy.ops.wm.recover_last_session()"])
        bpy.ops.wm.quit_blender()
        return {"FINISHED"}


class OpenPoDirectory(bpy.types.Operator):
    bl_idname = "bim.open_po_directory"
    bl_label = "Open Directory With .po Files"
    bl_options = set()

    def execute(self, context):
        import webbrowser

        webbrowser.open(BRANCHES_DIR)
        return {"FINISHED"}


class BBIM_PT_translations(bpy.types.Panel):
    bl_label = "BlenderBIM Translations"
    bl_idname = "BBIM_PT_translations"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        if not context.scene.translation_ui_is_loaded:
            layout.operator("bim.setup_translation_ui")
            return

        layout.operator("bim.reload_py_translations", icon="FILE_REFRESH")
        addon_enabled = is_addon_loaded(ADDON_NAME)
        layout.operator("bim.disable_enable_addon",
                        icon="QUIT" if addon_enabled else "PLUGIN",
                        text="Disable Addon And Restart Blender" if addon_enabled else "Enable Addon")
        layout.separator()
        layout.operator("bim.open_po_directory", icon="FILE_FOLDER")
        layout.operator("bim.convert_translations_to_po", icon="EXPORT")
        layout.operator("bim.update_translations_from_po", icon="IMPORT")


classes = (
    ReloadPyTranslations,
    ConvertTranslationsToPo,
    UpdateTranslationsFromPo,
    SetupTranslationUI,
    DisableEnableAddon,
    OpenPoDirectory,
    BBIM_PT_translations,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.translation_ui_is_loaded = bpy.props.BoolProperty(default=False)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.translation_ui_is_loaded
