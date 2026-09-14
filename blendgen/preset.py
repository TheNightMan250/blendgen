# =============================================================================
# BlendGen - JSON preset save / load (BO-7)
# =============================================================================
# Every PropertyGroup field exposed in the BlendGen sidebar is serialized to a
# JSON file inside Blender's user preset directory:
#     <scripts>/presets/blendgen/<name>.json
# Loading writes those values back onto ``context.scene.blendgen``.
# =============================================================================

import json
import os
import re

import bpy


PRESET_SUBDIR = "presets/blendgen"
PRESET_VERSION = 1


def preset_directory(create=True):
    """Return the absolute BlendGen preset directory, creating it when requested.

    ``bpy.utils.user_resource`` resolves to Blender's user scripts folder, which
    is the canonical location for add-on presets across platforms.
    """
    path = bpy.utils.user_resource("SCRIPTS", path=PRESET_SUBDIR, create=create)
    if not path:
        fallback = os.path.join(os.path.expanduser("~"), ".blendgen", "presets")
        if create:
            os.makedirs(fallback, exist_ok=True)
        return fallback
    return path


def sanitize_preset_name(name):
    """Return a filesystem-safe preset stem (no path separators or extension)."""
    stem = os.path.basename((name or "").strip())
    if stem.lower().endswith(".json"):
        stem = stem[:-5]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return stem or "default"


def preset_path(name, create_dir=True):
    """Return the absolute JSON path for a named preset."""
    return os.path.join(preset_directory(create=create_dir), sanitize_preset_name(name) + ".json")


def list_presets():
    """Return sorted preset stems available in the BlendGen preset directory."""
    directory = preset_directory(create=False)
    if not directory or not os.path.isdir(directory):
        return []
    names = []
    for entry in os.listdir(directory):
        if entry.lower().endswith(".json"):
            names.append(entry[:-5])
    names.sort(key=str.lower)
    return names


def serialize_settings(settings):
    """Dump every RNA property on the BlendGen PropertyGroup to a JSON-safe dict."""
    payload = {"blendgen_preset_version": PRESET_VERSION}
    for prop in settings.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type":
            continue
        value = getattr(settings, ident)
        payload[ident] = _to_json_value(value)
    return payload


def apply_settings(settings, payload):
    """Write values from a preset dict onto the live PropertyGroup.

    Unknown keys are ignored so presets remain forward-compatible when new
    properties are added. Type mismatches fall back to the current value.
    """
    if not isinstance(payload, dict):
        raise ValueError("Preset file does not contain a JSON object.")
    for prop in settings.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type" or ident not in payload:
            continue
        current = getattr(settings, ident)
        converted = _from_json_value(payload[ident], current)
        if converted is _UNCHANGED:
            continue
        # Blender 4.2+/5.x DIR_PATH properties reject a "//" prefix on setattr
        # even though the UI still accepts blend-relative paths. Resolve them.
        if isinstance(converted, str) and converted.startswith("//"):
            converted = bpy.path.abspath(converted)
        try:
            setattr(settings, ident, converted)
        except (TypeError, ValueError, OverflowError):
            continue


_UNCHANGED = object()


def _to_json_value(value):
    """Convert an RNA value to a JSON-serializable Python object."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_list"):
        return list(value.to_list())
    if hasattr(value, "__len__") and not isinstance(value, (bytes, bytearray)):
        try:
            return [ _to_json_value(item) for item in value ]
        except TypeError:
            return str(value)
    return str(value)


def _from_json_value(raw, current):
    """Coerce a JSON value back to the type of ``current``."""
    if isinstance(current, bool):
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return _UNCHANGED
    if isinstance(current, int) and not isinstance(current, bool):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return _UNCHANGED
    if isinstance(current, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return _UNCHANGED
    if isinstance(current, str):
        return "" if raw is None else str(raw)
    return raw


class PresetManager:
    """High-level save / load / list API used by the BlendGen operators."""

    def save(self, name, context):
        """Serialize ``context.scene.blendgen`` to ``<preset dir>/<name>.json``."""
        settings = context.scene.blendgen
        path = preset_path(name, create_dir=True)
        payload = serialize_settings(settings)
        payload["preset_name"] = sanitize_preset_name(name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return path

    def load(self, name, context):
        """Read a named preset and apply it to ``context.scene.blendgen``."""
        path = preset_path(name, create_dir=False)
        if not os.path.isfile(path):
            raise FileNotFoundError("Preset '%s' was not found at %s" % (name, path))
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        apply_settings(context.scene.blendgen, payload)
        return path

    def load_file(self, filepath, context):
        """Load a preset from an arbitrary JSON path (file-browser import)."""
        if not os.path.isfile(filepath):
            raise FileNotFoundError("Preset file '%s' does not exist." % filepath)
        with open(filepath, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        apply_settings(context.scene.blendgen, payload)
        return filepath

    def list(self):
        """Return available preset names."""
        return list_presets()
