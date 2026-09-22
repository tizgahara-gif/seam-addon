"""Auto Seam UV Equalizer Blender add-on."""

from __future__ import annotations

bl_info = {
    "name": "Auto Seam UV Equalizer",
    "author": "地図ヶ原",
    "version": (0, 11, 0),
    "blender": (5, 1, 2),
    "location": "View3D > Sidebar > Auto UV",
    "description": ("Topology-aware seam generation, UV unwrapping, weighted layout, "
                    "symmetry tools, and UV validation for production meshes."),
    "category": "UV",
}

import bpy  # noqa: E402
from bpy.app.handlers import persistent  # noqa: E402
from bpy.props import PointerProperty  # noqa: E402

from . import (operators, operators_protection, operators_seam, operators_symmetry,
               simple_workflow,
               operators_uv, operators_validation, properties, translations, ui)

CLASSES = (
    properties.AUTOSEAMUV_PG_settings,
    *simple_workflow.CLASSES,
    operators.AUTOSEAMUV_OT_mark_selected_region_boundary,
    operators.AUTOSEAMUV_OT_analyze_seams,
    operators.AUTOSEAMUV_OT_generate_seams,
    operators.AUTOSEAMUV_OT_detect_ring_strip,
    operators.AUTOSEAMUV_OT_unwrap_ring_strip,
    operators.AUTOSEAMUV_OT_mark_only,
    operators.AUTOSEAMUV_OT_unwrap_only,
    operators.AUTOSEAMUV_OT_unwrap_selected_faces,
    operators.AUTOSEAMUV_OT_weighted_island_layout,
    operators.AUTOSEAMUV_OT_shared_weighted_atlas,
    operators.AUTOSEAMUV_OT_pack_islands,
    operators.AUTOSEAMUV_OT_pack_selected_into_free_space,
    operators.AUTOSEAMUV_OT_auto_unwrap_pack,
    operators.AUTOSEAMUV_OT_mark_and_unwrap,
    operators.AUTOSEAMUV_OT_atlas_pack_selected_objects,
    operators.AUTOSEAMUV_OT_check_uv_overlap,
    operators.AUTOSEAMUV_OT_clear_uv_overlap_highlight,
    *operators_seam.CLASSES,
    *operators_symmetry.CLASSES,
    *operators_uv.CLASSES,
    *operators_protection.CLASSES,
    *operators_validation.CLASSES,
    *ui.CLASSES,
)

_SCENE_PROPERTY = "autoseamuv_settings"
_LIFECYCLE_KEY = "auto_seam_uv_equalizer.registration"
_GENERATION = object()
_registered_classes: list[type] = []
_translations_registered = False
_migration_retry_attempts = 0
_MIGRATION_MAX_RETRIES = 20
_MIGRATION_RETRY_INTERVAL = 0.1


def _registered_class(cls: type):
    """Return the registered class, including orphaned PropertyGroup RNA types."""
    if issubclass(cls, bpy.types.PropertyGroup):
        return bpy.types.PropertyGroup.bl_rna_get_subclass_py(cls.__name__, None)
    return getattr(bpy.types, cls.__name__, None)


def _remove_scene_property() -> None:
    """Remove the RNA pointer before its PropertyGroup can be unregistered."""
    if hasattr(bpy.types.Scene, _SCENE_PROPERTY):
        delattr(bpy.types.Scene, _SCENE_PROPERTY)


def _migration_available() -> bool:
    """Return whether this generation's Scene settings RNA still exists."""
    return hasattr(bpy.types.Scene, _SCENE_PROPERTY)


def _migrate_loaded_scenes() -> None:
    """Migrate every loaded Scene, without making one bad Scene stop the rest."""
    if not _migration_available():
        return

    for scene in bpy.data.scenes:
        settings = getattr(scene, _SCENE_PROPERTY, None)
        if settings is None:
            continue
        try:
            properties.migrate_legacy_settings(settings)
        except Exception as exc:
            # Migration is a compatibility aid, not a condition of add-on use.
            print(
                "Auto Seam UV Equalizer: failed to migrate legacy settings "
                f"for Scene {scene.name!r}: {exc!r}"
            )


def _restricted_data_is_active() -> bool:
    """Detect Blender's registration-time data proxy without parsing errors."""
    return type(bpy.data).__name__ == "_RestrictData"


def _deferred_migrate_current_file():
    """Timer callback which waits until Blender releases its data API."""
    global _migration_retry_attempts

    if not _migration_available():
        _migration_retry_attempts = 0
        return None
    if _restricted_data_is_active():
        _migration_retry_attempts += 1
        if _migration_retry_attempts < _MIGRATION_MAX_RETRIES:
            return _MIGRATION_RETRY_INTERVAL
        print(
            "Auto Seam UV Equalizer: legacy settings migration was deferred; "
            "it will retry when a .blend file is loaded."
        )
        _migration_retry_attempts = 0
        return None

    _migration_retry_attempts = 0
    try:
        _migrate_loaded_scenes()
    except Exception as exc:
        # In particular, do not turn optional migration into an enable failure.
        print(f"Auto Seam UV Equalizer: deferred legacy migration failed: {exc!r}")
    return None


@persistent
def _on_load_post(_filepath) -> None:
    """Migrate legacy settings whenever another blend file is loaded."""
    if not _migration_available():
        return
    try:
        _migrate_loaded_scenes()
    except Exception as exc:
        print(f"Auto Seam UV Equalizer: load_post legacy migration failed: {exc!r}")


def _make_cleanup(
    classes: tuple[type, ...],
    translations_are_registered: bool,
    load_handler,
    migration_timer,
):
    """Capture one generation's objects so module reload cannot change them."""
    def cleanup() -> None:
        if bpy.app.timers.is_registered(migration_timer):
            bpy.app.timers.unregister(migration_timer)
        if load_handler in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(load_handler)
        _remove_scene_property()
        if translations_are_registered:
            translations.unregister()
        for cls in reversed(classes):
            if _registered_class(cls) is cls:
                bpy.utils.unregister_class(cls)

    return cleanup


def _cleanup_previous_generation() -> None:
    """Prefer the previous generation's complete lifecycle when available."""
    previous = bpy.app.driver_namespace.get(_LIFECYCLE_KEY)
    if previous and previous.get("generation") is not _GENERATION:
        previous["cleanup"]()
        bpy.app.driver_namespace.pop(_LIFECYCLE_KEY, None)


def _validate_classes() -> None:
    if len(CLASSES) != len(set(CLASSES)):
        raise RuntimeError("Auto Seam UV Equalizer CLASSES contains duplicate class objects")
    names = [cls.__name__ for cls in CLASSES]
    if len(names) != len(set(names)):
        raise RuntimeError("Auto Seam UV Equalizer CLASSES contains duplicate class names")


def register() -> None:
    """Register add-on classes and scene properties."""
    global _migration_retry_attempts, _registered_classes, _translations_registered

    _validate_classes()
    _cleanup_previous_generation()

    # Remove a generation that predates lifecycle tracking.  bpy.types returns
    # the actual registered Python class and is safe to pass to unregister_class.
    # Its pointer owns an RNA reference and must disappear before the class.
    _remove_scene_property()
    for cls in reversed(CLASSES):
        registered = _registered_class(cls)
        if registered is not None and registered is not cls:
            bpy.utils.unregister_class(registered)
            remaining = _registered_class(cls)
            if remaining is not None:
                raise RuntimeError(
                    f"stale RNA class {cls.__name__!r} remained registered after cleanup"
                )

    registered_now: list[type] = []
    pointer_created = False
    translations_now = False
    handler_added = False
    timer_added = False
    try:
        for cls in CLASSES:
            if _registered_class(cls) is cls:
                continue
            bpy.utils.register_class(cls)
            registered_now.append(cls)

        setattr(
            bpy.types.Scene,
            _SCENE_PROPERTY,
            PointerProperty(type=properties.AUTOSEAMUV_PG_settings),
        )
        pointer_created = True
        translations.register()
        translations_now = True
        if _on_load_post not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_on_load_post)
            handler_added = True
        _migration_retry_attempts = 0
        if not bpy.app.timers.is_registered(_deferred_migrate_current_file):
            bpy.app.timers.register(_deferred_migrate_current_file, first_interval=0.0)
            timer_added = True
    except Exception:
        if timer_added and bpy.app.timers.is_registered(_deferred_migrate_current_file):
            bpy.app.timers.unregister(_deferred_migrate_current_file)
        if handler_added and _on_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_load_post)
        if pointer_created:
            _remove_scene_property()
        if translations_now:
            translations.unregister()
        for cls in reversed(registered_now):
            if _registered_class(cls) is cls:
                bpy.utils.unregister_class(cls)
        _registered_classes = []
        _translations_registered = False
        bpy.app.driver_namespace.pop(_LIFECYCLE_KEY, None)
        raise

    _registered_classes = list(CLASSES)
    _translations_registered = True
    bpy.app.driver_namespace[_LIFECYCLE_KEY] = {
        "generation": _GENERATION,
        "cleanup": _make_cleanup(
            tuple(CLASSES), True, _on_load_post, _deferred_migrate_current_file
        ),
        "load_handler": _on_load_post,
        "migration_timer": _deferred_migrate_current_file,
    }


def unregister() -> None:
    """Unregister add-on classes and scene properties."""
    global _registered_classes, _translations_registered

    state = bpy.app.driver_namespace.get(_LIFECYCLE_KEY)
    if state:
        state["cleanup"]()
        bpy.app.driver_namespace.pop(_LIFECYCLE_KEY, None)
        _translations_registered = False
    else:
        if bpy.app.timers.is_registered(_deferred_migrate_current_file):
            bpy.app.timers.unregister(_deferred_migrate_current_file)
        if _on_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_load_post)
        _remove_scene_property()
        if _translations_registered:
            translations.unregister()
            _translations_registered = False

    for cls in reversed(CLASSES):
        if _registered_class(cls) is cls:
            bpy.utils.unregister_class(cls)
    _registered_classes = []


if __name__ == "__main__":
    register()
