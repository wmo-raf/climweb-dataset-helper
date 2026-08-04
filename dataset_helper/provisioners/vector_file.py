"""Provisioner for layer_type=vector_file.

Pipeline — strict mirror of ``raster_file`` (delegates the publish step
to geomanager via ``create_layer_vector_file``):

  1. Download the file at ``entry.file_url`` to a temp path.
  2. If it is plain JSON (list of records), convert to GeoJSON by guessing
     latitude/longitude columns. GeoJSON files pass through unchanged.
  3. Create a ``VectorFileLayer`` (render_layers from the catalog, or auto
     from the geometry type peeked in the GeoJSON; legend; popup).
  4. Create a ``VectorUpload`` and let geomanager publish it
     (``create_layer_vector_file`` runs ``ogr_db_import``, creates the
     ``PgVectorTable`` and deletes the upload).
  5. Annotate ``PgVectorTable.properties`` for popup-enabled columns.
"""
import json
import logging
import os
import uuid

from django.core.files import File
from django.utils import timezone

from geomanager.models.vector_file import VectorFileLayer, VectorUpload

# ``create_layer_vector_file`` ships in the local geomanager source (branch
# with the helper) but is absent from older pip-installed versions. Make the
# import optional so the plugin still loads even when the bind-mount hasn't
# been wired up yet — provision() raises with a clear message at sync time.
try:
    from geomanager.utils.vector_utils import create_layer_vector_file
except ImportError:
    create_layer_vector_file = None

from ..models import PluginSettings
from ._shared import add_legend_kwargs, download_file, resolve_file_url, resolve_i18n

logger = logging.getLogger(__name__)


_LAT_KEYS = ('lat', 'latitude', 'lat_dd', 'latitude_dd', 'latitude_deg', 'y')
_LON_KEYS = ('lon', 'lng', 'long', 'longitude', 'lon_dd', 'longitude_dd', 'longitude_deg', 'x')


def provision(entry, dataset):
    """Materialise a VectorFileLayer + PgVectorTable from a catalog entry."""
    if create_layer_vector_file is None:
        raise RuntimeError(
            "geomanager.utils.vector_utils.create_layer_vector_file is missing — "
            "the plugin needs the local geomanager source mounted in the venv "
            "(e.g. 'pip install -e /geomanager' inside climweb-dev)."
        )
    url = resolve_file_url(entry.file_url)
    lang = PluginSettings.load().language

    download_path = download_file(url, suffix='.json', bearer=entry.file_bearer or None)
    geojson_path = None
    cleanup_paths = [download_path]
    try:
        geojson_path = _to_geojson(download_path)
        if geojson_path != download_path:
            cleanup_paths.append(geojson_path)

        # Build render_layers up front: either the catalog-provided JSON, or a
        # default scheme picked from the first feature's geometry type.
        render_layers = entry.render_layers_json or _default_render_layers(
            _peek_geom_type(geojson_path)
        )

        kwargs = dict(
            dataset=dataset,
            title=entry.layer_title or entry.title,
            default=True,
        )
        if render_layers:
            kwargs['render_layers'] = _normalize_render_layers(render_layers)
        if entry.legend_json:
            add_legend_kwargs(kwargs, entry.legend_json, VectorFileLayer, lang=lang)

        layer = VectorFileLayer.objects.create(**kwargs)

        # Force a .geojson filename for the upload — geomanager's
        # ogr_db_import dispatches on the file extension and only accepts
        # .zip / .geojson / .gpkg. The downloaded file may be named .json
        # (passed-through GeoJSON) or .json.geojson (converted), so we
        # rewrite the name explicitly here.
        upload_name = f"vector_{uuid.uuid4().hex[:12]}.geojson"
        with open(geojson_path, 'rb') as f:
            upload = VectorUpload.objects.create(
                dataset=dataset,
                file=File(f, name=upload_name),
            )

        time = timezone.now().replace(minute=0, second=0, microsecond=0)
        pg_table = create_layer_vector_file(layer, upload, time)

        new_props = _apply_popup_to_properties(
            pg_table.properties, entry.popup_config_json, lang=lang
        )
        if new_props != pg_table.properties:
            pg_table.properties = new_props
            pg_table.save(update_fields=['properties'])
    finally:
        for path in cleanup_paths:
            if path and os.path.exists(path):
                os.unlink(path)


def _peek_geom_type(geojson_path):
    """
    Read the GeoJSON just enough to know the first feature's geometry type,
    used to pick a default ``render_layers`` style. Returns ``''`` on failure
    so the caller gets an empty default and the admin can configure manually.
    """
    try:
        with open(geojson_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return ''
    if not isinstance(data, dict):
        return ''
    if data.get('type') == 'FeatureCollection':
        for feat in data.get('features') or []:
            geom = feat.get('geometry') if isinstance(feat, dict) else None
            if isinstance(geom, dict) and geom.get('type'):
                return str(geom['type']).upper()
    elif data.get('type') == 'Feature':
        geom = data.get('geometry')
        if isinstance(geom, dict) and geom.get('type'):
            return str(geom['type']).upper()
    return ''


# ---------------------------------------------------------------------------
# JSON → GeoJSON conversion
# ---------------------------------------------------------------------------


def _to_geojson(file_path):
    """
    If ``file_path`` is already GeoJSON (FeatureCollection or Feature), return
    it unchanged. Otherwise, expect a JSON list of records, guess the
    latitude/longitude columns (case-insensitive: lat/latitude/y vs
    lon/lng/longitude/x) and write a sibling ``.geojson`` file.
    Raises ``ValueError`` when the conversion isn't possible.
    """
    with open(file_path, encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        # Already GeoJSON: pass through.
        if data.get('type') in ('FeatureCollection', 'Feature'):
            return file_path
        # Common API envelope: ``{"success": true, "data": [...]}`` (or a dict
        # of records keyed by id). Unwrap to the inner records and continue
        # with the lat/lng-based conversion below.
        if 'success' in data and 'data' in data:
            inner = data['data']
            if isinstance(inner, list):
                data = inner
            elif isinstance(inner, dict):
                data = list(inner.values())
            else:
                raise ValueError(
                    "JSON envelope 'data' must be a list or dict of records, "
                    f"got {type(inner).__name__}"
                )

    if not isinstance(data, list):
        raise ValueError(
            "Vector JSON must be a GeoJSON FeatureCollection/Feature, a list "
            "of records, or {success, data: [...]} envelope"
        )
    sample = next((r for r in data if isinstance(r, dict)), None)
    if sample is None:
        raise ValueError("Vector JSON contains no record-shaped objects")

    keys_lc = {k.lower(): k for k in sample.keys()}
    lat_key = next((keys_lc[k] for k in _LAT_KEYS if k in keys_lc), None)
    lon_key = next((keys_lc[k] for k in _LON_KEYS if k in keys_lc), None)
    if not lat_key or not lon_key:
        raise ValueError(
            "Could not guess lat/lng columns from JSON record keys: "
            f"{sorted(sample.keys())}"
        )

    features = []
    skipped = 0
    for rec in data:
        if not isinstance(rec, dict):
            skipped += 1
            continue
        try:
            lat = float(rec[lat_key])
            lon = float(rec[lon_key])
        except (TypeError, ValueError, KeyError):
            skipped += 1
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            skipped += 1
            continue
        props = {k: v for k, v in rec.items() if k not in (lat_key, lon_key)}
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': props,
        })

    if not features:
        raise ValueError(f"No valid features built from JSON records (skipped {skipped})")
    if skipped:
        logger.info("Skipped %d records without usable lat/%s columns", skipped, lat_key)

    out_path = file_path + '.geojson'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': features}, f)
    return out_path


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------


def _default_render_layers(geom_type):
    """
    Build a minimal ``render_layers`` StreamField value from the detected
    PostGIS geometry type so the layer renders something out of the box.
    Returns a Python list (not JSON string). Empty list when geom_type
    is unknown — admin can configure it manually afterwards.
    """
    g = (geom_type or '').upper()
    if 'POINT' in g:
        return [_block('circle', {
            'paint': {
                'circle_color': '#3388ff',
                'circle_opacity': 0.85,
                'circle_radius': 5.0,
                'circle_stroke_color': '#ffffff',
                'circle_stroke_width': 1.0,
            },
        })]
    if 'LINESTRING' in g:
        return [_block('line', {
            'paint': {
                'line_color': '#3388ff',
                'line_opacity': 1.0,
                'line_width': 2.0,
            },
        })]
    if 'POLYGON' in g:
        return [_block('fill', {
            'paint': {
                'fill_color': '#3388ff',
                'fill_opacity': 0.4,
                'fill_outline_color': '#1d4ed8',
                'fill_antialias': True,
            },
        })]
    return []


def _block(block_type, value):
    return {'type': block_type, 'id': str(uuid.uuid4()), 'value': value}


def _normalize_render_layers(render_layers):
    """
    Make sure each render_layer dict has an ``id`` (Wagtail StreamField
    expects one) and is shaped as ``{type, id, value}``. ``value`` keys are
    normalized from kebab-case (maplibre style, e.g. ``icon-image``) to
    snake_case (geomanager block field names, e.g. ``icon_image``) at every
    depth, so admins can paste maplibre-style snippets directly into the
    catalog JSON.

    Two shorthand forms are accepted for each render_layer:

    1. Maplibre/StreamField style (recommended for icon/text layers)::

        {"type": "icon",
         "value": {
           "layout": {"icon-image": "airport", "icon-size": 1.2},
           "paint":  {"icon-color": "#222"}}
         }

    2. Flat shorthand (same as before)::

        {"type": "fill", "paint": {"fill-color": "#3388ff"}}
    """
    out = []
    for item in render_layers or []:
        if not isinstance(item, dict):
            continue
        block_type = item.get('type')
        if not block_type:
            continue
        value = item.get('value')
        if value is None:
            value = {k: v for k, v in item.items() if k not in ('type', 'id')}
        out.append({
            'type': block_type,
            'id': item.get('id') or str(uuid.uuid4()),
            'value': _kebab_to_snake_keys(value),
        })
    return out


def _kebab_to_snake_keys(value):
    """
    Recursively convert all dict keys from kebab-case to snake_case and drop
    keys whose value is ``None`` (unset). Null entries from the catalog JSON
    must not be forwarded to maplibre, where they trigger ``array expected,
    null found`` style errors on optional layout/paint properties.
    """
    if isinstance(value, dict):
        return {
            k.replace('-', '_'): _kebab_to_snake_keys(v)
            for k, v in value.items()
            if v is not None
        }
    if isinstance(value, list):
        return [_kebab_to_snake_keys(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Popup
# ---------------------------------------------------------------------------


def _apply_popup_to_properties(properties, popup_config, lang='en'):
    """
    Annotate ``PgVectorTable.properties`` rows with ``popup=True`` and an
    optional localised ``label`` for every column listed in ``popup_config``.
    Unknown ``data_key`` entries are logged and ignored.
    """
    properties = list(properties or [])
    if not popup_config or not isinstance(popup_config, list):
        return properties

    by_name = {(p.get('name') or ''): p for p in properties}
    for item in popup_config:
        data_key = (item.get('data_key') or '').strip()
        if not data_key:
            continue
        column = by_name.get(data_key)
        if column is None:
            logger.warning(
                "popup_config data_key '%s' not found in vector file columns; ignoring.",
                data_key,
            )
            continue
        column['popup'] = True
        label = resolve_i18n(item.get('label'), lang)
        if label:
            column['label'] = label

    return properties
