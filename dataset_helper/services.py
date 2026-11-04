import hashlib
import json as json_module
import logging
import os
import re
import urllib.request
import uuid

from django.contrib.staticfiles import finders
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from geomanager.models.core import Category, Dataset, Metadata, SubCategory
from geomanager.models.raster_style import ColorValue, RasterStyle
from geomanager.models.raster_tile import RasterTileLayer
from geomanager.models.vector_tile import VectorTileLayer
from geomanager.models.wms import WmsLayer, WmsRequestLayer, WmsRequestParam

try:
    from geomanager.models.raster_file import RasterFileLayer
except ImportError:
    RasterFileLayer = None

# raster_cog is on a separate geomanager branch — make the import optional so
# the plugin still loads on branches without it. _provision_raster_cog raises
# at sync time if the layer type is used while the model is missing.
try:
    from geomanager.models.raster_cog import RasterCOGLayer
except ImportError:
    RasterCOGLayer = None

# Same for openmeteo: _provision_openmeteo raises at sync time without it.
try:
    from geomanager.models.openmeteo import OpenMeteoLayer
except ImportError:
    OpenMeteoLayer = None

from .models import CatalogEntry, CatalogState, PluginSettings
from .provisioners import PROVISIONERS as _PACKAGED_PROVISIONERS
from .provisioners._shared import (
    DEFAULT_RASTER_PALETTE,
    add_legend_kwargs,
    download_file,
    resolve_file_url,
    resolve_i18n,
)

logger = logging.getLogger(__name__)


ECMWF_TOKEN_PLACEHOLDER = '{ECMWF_TOKEN}'

# Highest catalog schema_version this code knows how to parse.
SUPPORTED_CATALOG_SCHEMA_VERSION = 1

# Fields hashed into CatalogEntry.source_hash. These are the fields that
# originate from the catalog JSON; state fields (origin, enabled,
# dataset_id, timestamps, hashes themselves) are deliberately excluded
# so the hash stays stable when local state changes.
SOURCE_HASH_FIELDS = (
    'title', 'summary',
    'layer_type',
    'category_title', 'category_icon', 'subcategory_title',
    'layer_name', 'wms_url', 'public', 'layer_title', 'extra_params_json',
    'tile_url', 'is_pmtiles',
    'file_url', 'file_bearer',
    'cog_url_template', 'cog_time_start', 'cog_time_end',
    'cog_time_step_value', 'cog_time_step_unit', 'cog_date_format',
    'raster_style_json', 'render_layers_json', 'popup_config_json', 'popup',
    'legend_json', 'legend_from_capabilities',
    'meta_source', 'meta_resolution', 'meta_geographic_coverage',
    'meta_license', 'meta_frequency_of_update', 'meta_function',
    'meta_overview', 'meta_learn_more',
    'multi_temporal', 'near_realtime',
    'initial_visible', 'auto_update_interval',
    'category_order', 'subcategory_order', 'entry_order',
)

# Catalog-derived fields added after entries were first loaded. They are
# hashed only when set, so adding one leaves the hash of every entry that
# does not use it unchanged, instead of flagging the whole catalog as updated.
OPTIONAL_SOURCE_HASH_FIELDS = (
    'openmeteo_base_url', 'openmeteo_domain', 'openmeteo_variable',
    'openmeteo_date_format',
    'current_time_method',
)

DEFAULT_CURRENT_TIME_METHOD = 'latest_from_source'


def compute_source_hash(values):
    """
    Return a stable sha256 hex digest of the catalog-derived fields of an
    entry. Accepts a dict (the ``defaults`` payload for ``update_or_create``)
    or a ``CatalogEntry`` instance.
    """
    if isinstance(values, dict):
        get = values.get
    else:
        def get(k):
            return getattr(values, k, None)
    payload = {k: get(k) for k in SOURCE_HASH_FIELDS}
    payload.update({k: get(k) for k in OPTIONAL_SOURCE_HASH_FIELDS if get(k)})
    serialized = json_module.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _project_provisioned_layer(dataset):
    """
    Return a canonical dict of the layer-type-specific Climweb object
    attached to ``dataset``. Used by ``compute_provisioned_hash``.

    Only fields the plugin actually writes during provisioning are
    projected. Complex StreamFields (popup_config) and RasterStyle
    relations are skipped for v1 — the hash will not detect edits
    confined to those, which is an acceptable initial limitation.
    """
    lt = dataset.layer_type
    if lt == 'wms':
        wms = WmsLayer.objects.filter(dataset=dataset).first()
        if wms is None:
            return {}
        return {
            'base_url': wms.base_url,
            'version': wms.version,
            'format': wms.format,
            'srs': wms.srs,
            'width': wms.width,
            'height': wms.height,
            'transparent': wms.transparent,
            'popup': wms.popup,
            'legend_from_capabilities': wms.legend_from_capabilities,
            'request_layers': sorted(
                WmsRequestLayer.objects.filter(layer=wms).values_list('name', flat=True)
            ),
            'request_params': sorted(
                (p.name, p.value)
                for p in WmsRequestParam.objects.filter(layer=wms)
            ),
        }
    if lt == 'raster_tile':
        rt = RasterTileLayer.objects.filter(dataset=dataset).first()
        if rt is None:
            return {}
        return {'base_url': rt.base_url}
    if lt == 'vector_tile':
        vt = VectorTileLayer.objects.filter(dataset=dataset).first()
        if vt is None:
            return {}
        return {
            'base_url': vt.base_url,
            'is_pmtiles': vt.is_pmtiles,
            'use_render_layers_json': vt.use_render_layers_json,
            'render_layers_json': vt.render_layers_json,
        }
    if lt == 'raster_cog' and RasterCOGLayer is not None:
        rc = RasterCOGLayer.objects.filter(dataset=dataset).first()
        if rc is None:
            return {}
        return {
            'url_template': rc.url_template,
            'time_start': rc.time_start,
            'time_end': rc.time_end,
            'time_step_value': rc.time_step_value,
            'time_step_unit': rc.time_step_unit,
            'date_format': rc.date_format,
        }
    if lt == 'openmeteo' and OpenMeteoLayer is not None:
        om = OpenMeteoLayer.objects.filter(dataset=dataset).first()
        if om is None:
            return {}
        return {
            'base_url': om.base_url,
            'domain': om.domain,
            'variable': om.variable,
            'date_format': om.date_format,
        }
    if lt == 'raster_file' and RasterFileLayer is not None:
        # The list of ingested LayerRasterFile rows changes over time as new
        # frames arrive — including them would make the hash drift on every
        # ingest. Hash only the stable layer-level fields.
        rf = RasterFileLayer.objects.filter(dataset=dataset).first()
        if rf is None:
            return {}
        return {'title': rf.title}
    return {}


def compute_provisioned_hash(dataset_id):
    """
    Return a stable sha256 hex digest of the current state of the Climweb
    Dataset (and the layer-type-specific objects) identified by ``dataset_id``.
    Returns '' if the Dataset no longer exists.
    """
    if dataset_id is None:
        return ''
    dataset = Dataset.objects.filter(id=dataset_id).first()
    if dataset is None:
        return ''

    payload = {
        'title': dataset.title,
        'summary': dataset.summary or '',
        'layer_type': dataset.layer_type,
        'public': dataset.public,
        'multi_temporal': dataset.multi_temporal,
        'near_realtime': dataset.near_realtime,
        'initial_visible': dataset.initial_visible,
        'auto_update_interval': dataset.auto_update_interval,
    }
    # Left out at its default, like OPTIONAL_SOURCE_HASH_FIELDS, so the
    # baseline of the datasets provisioned before it was set stays valid.
    if dataset.current_time_method != DEFAULT_CURRENT_TIME_METHOD:
        payload['current_time_method'] = dataset.current_time_method

    metadata = dataset.metadata
    if metadata is not None:
        payload['metadata'] = {
            'source': metadata.source or '',
            'function': metadata.function or '',
            'resolution': metadata.resolution or '',
            'geographic_coverage': metadata.geographic_coverage or '',
            'license': metadata.license or '',
            'frequency_of_update': metadata.frequency_of_update or '',
            'overview': metadata.overview or '',
            'learn_more': metadata.learn_more or '',
        }

    payload['layer'] = _project_provisioned_layer(dataset)

    serialized = json_module.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

EMBEDDED_CATALOG_STATIC_PATH = 'dataset_helper/catalog.json'

# (path, mtime) -> (version, schema_version). Avoids re-parsing the 3MB
# catalog on every admin page load; invalidates automatically when the
# file is replaced by a plugin upgrade.
_embedded_version_cache = {}


def _read_embedded_catalog():
    """
    Read and parse the bundled catalog.json from disk.
    Returns (data, path). Raises FileNotFoundError if missing,
    ValueError (JSONDecodeError) if not valid JSON.
    """
    path = finders.find(EMBEDDED_CATALOG_STATIC_PATH)
    if not path or not os.path.exists(path):
        raise FileNotFoundError(
            f"Embedded catalog not found at static path "
            f"'{EMBEDDED_CATALOG_STATIC_PATH}'"
        )
    with open(path, 'r', encoding='utf-8') as f:
        return json_module.load(f), path


def get_embedded_catalog_version():
    """
    Return (version, schema_version) of the bundled catalog.json.
    Returns ('', 0) if the file is missing, unparseable, or has no version.
    """
    path = finders.find(EMBEDDED_CATALOG_STATIC_PATH)
    if not path or not os.path.exists(path):
        return ('', 0)

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ('', 0)

    cached = _embedded_version_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        data, _ = _read_embedded_catalog()
    except (FileNotFoundError, OSError, ValueError) as e:
        logger.warning("Failed to read embedded catalog at %s: %s", path, e)
        return ('', 0)

    result = (
        (data.get('version') or '').strip(),
        int(data.get('schema_version') or 0),
    )
    _embedded_version_cache[path] = (mtime, result)
    return result


def load_embedded_catalog(conflict_policy='overwrite'):
    """
    Load the bundled catalog.json directly from disk into the CatalogEntry
    table. Bypasses the browser/static-handler round trip so we always
    process the file currently on disk, never a stale cached/collected
    copy.

    ``conflict_policy`` controls what happens when an entry's catalog
    content has changed AND the provisioned Climweb Dataset has been
    edited locally:
      - 'skip'      : keep local edits, hold off the catalog change
      - 'overwrite' : adopt the new catalog content (default)

    The embedded catalog is authoritative for its scope: config-origin
    entries that disappear from the JSON are marked ``enabled=False``
    so the next Climweb sync deprovisions them.

    Returns the stats dict from load_catalog_from_config.
    """
    data, _ = _read_embedded_catalog()
    return load_catalog_from_config(
        data,
        conflict_policy=conflict_policy,
        mark_removed=True,
    )


def preview_embedded_catalog():
    """
    Dry-run: walk the embedded catalog JSON exactly like a real load
    would, but classify each entry into a bucket instead of writing.

    Buckets returned:
      - to_add        : product_code in JSON, not in DB
      - clean_update  : source_hash changed, no local drift  → safe to apply
      - local_drift   : source_hash unchanged, but Climweb Dataset diverged
                        from its provisioned baseline (admin edited it)
      - conflict      : source_hash changed AND Climweb Dataset diverged
      - unchanged     : nothing to do for this entry
      - to_remove     : origin=config entry in DB, absent from JSON

    Returns a dict with the buckets plus the loader's error/skip counters.
    """
    data, _ = _read_embedded_catalog()
    catalog_version = (data.get('version') or '').strip()
    catalog_schema = int(data.get('schema_version') or 0)

    incoming = []  # [(product_code, defaults)]
    def collect(product_code, defaults, stats):
        incoming.append((product_code, defaults))

    base_stats = load_catalog_from_config(data, handle_entry=collect)

    incoming_codes = {pc for pc, _ in incoming}
    existing = {
        e.product_code: e
        for e in CatalogEntry.objects.filter(origin=CatalogEntry.ORIGIN_CONFIG)
    }

    to_add, clean_update, local_drift, conflict, to_remove = [], [], [], [], []
    unchanged_count = 0

    def _describe(product_code, defaults, entry=None):
        return {
            'product_code': product_code,
            'title': (defaults.get('title') if defaults else None) or (entry.title if entry else ''),
            'category': (defaults.get('category_title') if defaults else None) or (entry.category_title if entry else ''),
            'subcategory': (defaults.get('subcategory_title') if defaults else None) or (entry.subcategory_title if entry else ''),
        }

    for product_code, defaults in incoming:
        incoming_hash = compute_source_hash(defaults)
        entry = existing.get(product_code)

        if entry is None:
            to_add.append(_describe(product_code, defaults))
            continue

        source_changed = incoming_hash != entry.source_hash

        local_drifted = False
        if entry.dataset_id and entry.provisioned_hash:
            current = compute_provisioned_hash(entry.dataset_id)
            local_drifted = (current != entry.provisioned_hash)

        info = _describe(product_code, defaults, entry)

        if source_changed and local_drifted:
            conflict.append(info)
        elif source_changed:
            clean_update.append(info)
        elif local_drifted:
            local_drift.append(info)
        else:
            unchanged_count += 1

    for product_code, entry in existing.items():
        if product_code not in incoming_codes:
            to_remove.append(_describe(product_code, None, entry))

    return {
        'catalog_version': catalog_version,
        'catalog_schema_version': catalog_schema,
        'to_add': to_add,
        'clean_update': clean_update,
        'local_drift': local_drift,
        'conflict': conflict,
        'to_remove': to_remove,
        'unchanged': unchanged_count,
        'errors': base_stats.get('errors', []),
        'skipped_estation': base_stats.get('skipped_estation', 0),
        'skipped_ecmwf_no_token': base_stats.get('skipped_ecmwf_no_token', 0),
        'skipped_out_of_coverage': base_stats.get('skipped_out_of_coverage', 0),
    }


def _valid_current_time_method(value):
    """Return ``value`` if GeoManager knows it as a Dataset.current_time_method, else ''."""
    known = {choice for choice, _label in Dataset.CURRENT_TIME_METHOD_CHOICES}
    return value if value in known else ''


def _point_in_ring(x, y, ring):
    """Ray casting: whether (x, y) lies inside the closed ``ring``."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _segments_cross(a, b, c, d):
    """Whether segments ab and cd intersect (touching counts)."""
    def orientation(p, q, r):
        value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (value > 0) - (value < 0)

    def on_segment(p, q, r):
        return (min(p[0], q[0]) <= r[0] <= max(p[0], q[0])
                and min(p[1], q[1]) <= r[1] <= max(p[1], q[1]))

    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    # collinear
    return ((o1 == 0 and on_segment(a, b, c)) or (o2 == 0 and on_segment(a, b, d))
            or (o3 == 0 and on_segment(c, d, a)) or (o4 == 0 and on_segment(c, d, b)))


def _ring_intersects_box(ring, west, south, east, north):
    if any(west <= x <= east and south <= y <= north for x, y in ring):
        return True
    # no ring vertex in the box: they overlap if the box is inside the ring,
    # or if a ring edge crosses the box
    if _point_in_ring((west + east) / 2, (south + north) / 2, ring):
        return True
    corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    return any(
        _segments_cross(a, b, c, d)
        for a, b in zip(ring, ring[1:])
        for c, d in zip(corners, corners[1:])
    )


def _coverage_intersects_country(coverage, country_bbox):
    """
    Whether a layer's ``coverage`` (closed [lon, lat] ring of the area it has
    data for, given by regional layers of the catalog) overlaps the country
    bounding box from the plugin settings ([south, north, west, east]).
    Layers without coverage, or a site without a country, always pass.
    """
    if not coverage or not country_bbox or len(country_bbox) != 4:
        return True
    try:
        ring = [(float(lon), float(lat)) for lon, lat in coverage]
        south, north, west, east = (float(v) for v in country_bbox)
    except (TypeError, ValueError):
        return True
    # Rings crossing the antimeridian keep increasing longitudes past ±180:
    # also try the box one turn east and west.
    return any(
        _ring_intersects_box(ring, west + shift, south, east + shift, north)
        for shift in (0, 360, -360)
    )


def _parse_iso_dt(value):
    """Parse an ISO-8601 datetime string (supports trailing Z). Returns None on failure."""
    if not value:
        return None
    if isinstance(value, str) and value.endswith('Z'):
        value = value[:-1] + '+00:00'
    return parse_datetime(value) if isinstance(value, str) else None


def _apply_ecmwf_token(wms_url, token):
    """
    Apply the configured ECMWF token to an eccharts WMS URL.

    Rules (only for URLs containing 'eccharts.ecmwf.int'):
      - token=public in URL:
          * token configured -> replace 'public' with the token
          * no token         -> leave URL unchanged
      - token={ECMWF_TOKEN} placeholder in URL:
          * token configured -> replace placeholder with the token; mark as non-public
          * no token         -> skip (cannot sync a private layer without a token)

    Returns (new_url, public, skip).
    Non-ECMWF URLs are returned unchanged with public=True, skip=False.
    """
    if 'eccharts.ecmwf.int' not in wms_url:
        return wms_url, True, False

    has_token = bool(token)

    if ECMWF_TOKEN_PLACEHOLDER in wms_url:
        if has_token:
            return wms_url.replace(ECMWF_TOKEN_PLACEHOLDER, token), False, False
        return wms_url, False, True

    if 'token=public' in wms_url:
        if has_token:
            return re.sub(r'(token=)[^&]*', rf'\g<1>{token}', wms_url), True, False
        return wms_url, True, False

    return wms_url, True, False


def _fetch_estation_product_ids(estation_url):
    """
    Fetch the local eStation /collections endpoint and return a set of product_id values.
    Returns None if estation_url is empty (meaning: no filtering).
    """
    if not estation_url:
        return None

    collections_url = estation_url.rstrip('/') + '/collections'
    try:
        req = urllib.request.Request(collections_url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json_module.loads(resp.read().decode('utf-8'))
        products = data.get('products', [])
        return {p['product_id'] for p in products if p.get('product_id')}
    except Exception as e:
        logger.warning("Failed to fetch eStation collections from %s: %s", collections_url, e)
        return None


def _substitute_estation_url(wms_url, estation_url):
    """
    Replace global eStation WMS base URL with the local eStation URL + /webservices.
    """
    if estation_url and 'estation' in wms_url.lower():
        return estation_url.rstrip('/') + '/webservices'
    return wms_url


def load_catalog_from_config(json_data, handle_entry=None, conflict_policy='overwrite', mark_removed=False):
    """
    Parse a config JSON and populate the CatalogEntry table.

    Supports two formats:
    1. Nested: {"categories": [{"title":..., "subcategories": [{"datasets": [...]}]}]}
    2. Flat products: {"products": [{"category":..., "product_id":..., "descriptive_name":..., "wms_getmap_url":...}]}

    Applies plugin settings: language resolution, ECMWF token substitution,
    and eStation local product filtering.

    ``handle_entry`` is the callback invoked for every layer found in the
    JSON; it receives ``(product_code, defaults, stats)``. Defaults to a
    policy-aware wrapper around ``_upsert_entry``. The dry-run preview
    path passes a collector here instead, so no writes happen.

    ``conflict_policy`` is forwarded to ``_upsert_entry`` (only meaningful
    on the default real-write path):
      - 'overwrite' : always apply catalog content (default; matches the
                      historical behavior of the textarea-paste flow)
      - 'skip'      : skip entries whose Climweb Dataset diverged locally

    ``mark_removed`` (default False, set to True by the embedded-catalog
    loader): after the walk, ``origin=config`` entries that did not
    appear in the JSON are disabled (so the next sync deprovisions
    them). The textarea-paste path leaves this off — a paste is not
    necessarily authoritative for the whole catalog.

    Returns stats dict with created/updated/unchanged/conflict_skipped/removed.
    """
    stats = {
        'created': 0,
        'updated': 0,
        'unchanged': 0,
        'conflict_skipped': 0,
        'removed': 0,
        'skipped_estation': 0,
        'skipped_ecmwf_no_token': 0,
        'skipped_out_of_coverage': 0,
        'errors': [],
    }

    version = (json_data.get('version') or '').strip()
    schema_version = json_data.get('schema_version')
    if schema_version is not None and schema_version > SUPPORTED_CATALOG_SCHEMA_VERSION:
        stats['errors'].append(
            f"Unsupported catalog schema_version={schema_version}. "
            f"This plugin supports up to schema_version={SUPPORTED_CATALOG_SCHEMA_VERSION}."
        )
        return stats

    settings = PluginSettings.load()
    lang = settings.language
    ecmwf_token = settings.ecmwf_token
    estation_product_ids = _fetch_estation_product_ids(settings.estation_url)

    estation_url = settings.estation_url

    real_write = handle_entry is None
    seen_codes = set() if mark_removed else None

    if real_write:
        def _default_handler(pc, defaults, stats):
            _upsert_entry(pc, defaults, stats, conflict_policy=conflict_policy)
            if seen_codes is not None:
                seen_codes.add(pc)
        handle_entry = _default_handler
    elif seen_codes is not None:
        original = handle_entry
        def _tracking_wrapper(pc, defaults, stats):
            original(pc, defaults, stats)
            seen_codes.add(pc)
        handle_entry = _tracking_wrapper

    if json_data.get('categories'):
        _load_nested_format(json_data, stats, lang, ecmwf_token, estation_product_ids, estation_url, handle_entry,
                            country_bbox=settings.country_bbox)
    elif json_data.get('products'):
        _load_products_format(json_data, stats, lang, ecmwf_token, estation_product_ids, estation_url, handle_entry)
    else:
        stats['errors'].append(
            'Unrecognized format: expected top-level "categories" (nested format) '
            'or "products" (flat format).'
        )

    if real_write and seen_codes is not None:
        # Disable enabled config-origin entries that disappeared from the JSON.
        # Bulk .update() bypasses auto_now, so set updated_at explicitly.
        removed = (
            CatalogEntry.objects
            .filter(origin=CatalogEntry.ORIGIN_CONFIG, enabled=True)
            .exclude(product_code__in=seen_codes)
            .update(enabled=False, updated_at=timezone.now())
        )
        stats['removed'] = removed

    if real_write and stats['created'] + stats['updated'] + stats['unchanged'] > 0:
        state = CatalogState.load()
        state.loaded_version = version
        state.loaded_schema_version = schema_version or 0
        state.loaded_at = timezone.now()
        state.save()

    return stats


def _load_nested_format(json_data, stats, lang='en', ecmwf_token='', estation_product_ids=None, estation_url='', handle_entry=None,
                        country_bbox=None):
    """
    Load from the nested categories > subcategories > datasets > layers format.

    Layers with a ``coverage`` footprint that misses ``country_bbox`` (regional
    weather models, …) are skipped.
    """
    if handle_entry is None:
        handle_entry = _upsert_entry

    def is_estation_layer(layer_name):
        """Check if a layer_name is an eStation product."""
        if estation_product_ids is None:
            return True  # No filtering
        return layer_name in estation_product_ids

    entry_counter = 0

    for cat_idx, cat_data in enumerate(json_data.get('categories', [])):
        cat_title = resolve_i18n(cat_data.get('title', ''), lang)
        cat_icon = cat_data.get('icon', 'map')

        for subcat_idx, subcat_data in enumerate(cat_data.get('subcategories', [])):
            subcat_title = resolve_i18n(subcat_data.get('title', ''), lang)

            for dataset_data in subcat_data.get('datasets', []):
                layers_data = dataset_data.get('layers', [])
                metadata = dataset_data.get('metadata', {})

                for layer_data in layers_data:
                    layer_type = layer_data.get('type', 'wms')
                    dataset_title = resolve_i18n(dataset_data.get('title', '?'), lang)

                    if not _coverage_intersects_country(layer_data.get('coverage'), country_bbox):
                        stats['skipped_out_of_coverage'] += 1
                        continue

                    public = True

                    # --- Validate required fields per type ---
                    if layer_type == 'wms':
                        layer_name = layer_data.get('layer_name', '')
                        wms_url = layer_data.get('wms_url', '')
                        if not layer_name or not wms_url:
                            stats['errors'].append(
                                f"Skipping WMS layer in '{cat_title}/{subcat_title}/"
                                f"{dataset_title}': missing layer_name or wms_url"
                            )
                            continue

                        # eStation filtering
                        if estation_product_ids is not None and 'estation' in wms_url.lower():
                            if not is_estation_layer(layer_name):
                                stats['skipped_estation'] += 1
                                continue

                        wms_url, public, skip = _apply_ecmwf_token(wms_url, ecmwf_token)
                        if skip:
                            stats['skipped_ecmwf_no_token'] += 1
                            continue

                        wms_url = _substitute_estation_url(wms_url, estation_url)
                        product_code = layer_name

                    elif layer_type in ('raster_tile', 'vector_tile'):
                        tile_url = layer_data.get('tile_url', '')
                        if not tile_url:
                            stats['errors'].append(
                                f"Skipping {layer_type} layer in '{cat_title}/{subcat_title}/"
                                f"{dataset_title}': missing tile_url"
                            )
                            continue
                        product_code = f"{layer_type}_{hashlib.md5(tile_url.encode()).hexdigest()[:12]}"

                    elif layer_type in ('raster_file', 'vector_file'):
                        file_url = layer_data.get('url', '')
                        if not file_url:
                            stats['errors'].append(
                                f"Skipping {layer_type} layer in '{cat_title}/{subcat_title}/"
                                f"{dataset_title}': missing url"
                            )
                            continue
                        product_code = f"{layer_type}_{hashlib.md5(file_url.encode()).hexdigest()[:12]}"

                    elif layer_type == 'raster_cog':
                        cog_url = layer_data.get('url_template', '')
                        time_start_raw = layer_data.get('time_start', '')
                        time_end_raw = layer_data.get('time_end', '')
                        if not cog_url or not time_start_raw or not time_end_raw:
                            stats['errors'].append(
                                f"Skipping raster_cog layer in '{cat_title}/{subcat_title}/"
                                f"{dataset_title}': missing url_template, time_start or time_end"
                            )
                            continue
                        product_code = f"raster_cog_{hashlib.md5(cog_url.encode()).hexdigest()[:12]}"

                    elif layer_type == 'openmeteo':
                        om_domain = layer_data.get('domain', '')
                        om_variable = layer_data.get('variable', '')
                        if not om_domain or not om_variable:
                            stats['errors'].append(
                                f"Skipping openmeteo layer in '{cat_title}/{subcat_title}/"
                                f"{dataset_title}': missing domain or variable"
                            )
                            continue
                        product_code = f"openmeteo_{om_domain}_{om_variable}"

                    else:
                        stats['errors'].append(
                            f"Skipping layer in '{cat_title}/{subcat_title}/"
                            f"{dataset_title}': unknown type '{layer_type}'"
                        )
                        continue

                    defaults = {
                        'title': resolve_i18n(dataset_data.get('title', ''), lang) or product_code,
                        'summary': resolve_i18n(dataset_data.get('summary', ''), lang),
                        'category_title': cat_title,
                        'category_icon': cat_icon,
                        'subcategory_title': subcat_title,
                        'category_order': cat_idx,
                        'subcategory_order': subcat_idx,
                        'entry_order': entry_counter,
                        'layer_type': layer_type,
                        'layer_name': layer_data.get('layer_name', ''),
                        'wms_url': wms_url if layer_type == 'wms' else '',
                        'public': public,
                        'layer_title': resolve_i18n(layer_data.get('title', ''), lang),
                        'tile_url': layer_data.get('tile_url', ''),
                        'is_pmtiles': bool(layer_data.get('is_pmtiles', False)),
                        'file_url': layer_data.get('url', ''),
                        'file_bearer': (layer_data.get('bearer') or '').strip(),
                        'cog_url_template': layer_data.get('url_template', '') if layer_type == 'raster_cog' else '',
                        'cog_time_start': _parse_iso_dt(layer_data.get('time_start')) if layer_type == 'raster_cog' else None,
                        'cog_time_end': _parse_iso_dt(layer_data.get('time_end')) if layer_type == 'raster_cog' else None,
                        'cog_time_step_value': int(layer_data.get('time_step_value', 1)) if layer_type == 'raster_cog' else 1,
                        'cog_time_step_unit': layer_data.get('time_step_unit', 'years') if layer_type == 'raster_cog' else 'years',
                        'cog_date_format': layer_data.get('date_format', '') if layer_type == 'raster_cog' else '',
                        'openmeteo_base_url': (layer_data.get('base_url') or '').rstrip('/') if layer_type == 'openmeteo' else '',
                        'openmeteo_domain': layer_data.get('domain', '') if layer_type == 'openmeteo' else '',
                        'openmeteo_variable': layer_data.get('variable', '') if layer_type == 'openmeteo' else '',
                        'openmeteo_date_format': layer_data.get('date_format', '') if layer_type == 'openmeteo' else '',
                        'raster_style_json': layer_data.get('raster_style') or None,
                        'render_layers_json': layer_data.get('render_layers') or None,
                        'popup_config_json': layer_data.get('popup_config') or None,
                        'popup': bool(layer_data.get('popup', False)),
                        'legend_from_capabilities': bool(layer_data.get('legend_from_capabilities', False)),
                        'extra_params_json': layer_data.get('extra_params') or None,
                        'legend_json': layer_data.get('legend') or None,
                        'multi_temporal': dataset_data.get('multi_temporal', True),
                        'near_realtime': dataset_data.get('near_realtime', False),
                        'initial_visible': dataset_data.get('initial_visible', False),
                        'auto_update_interval': dataset_data.get('auto_update_interval', None),
                        'current_time_method': _valid_current_time_method(dataset_data.get('current_time_method')),
                        # selection state of a new entry only, see _upsert_entry
                        'enabled': bool(dataset_data.get('enabled', True)),
                        'origin': CatalogEntry.ORIGIN_CONFIG,
                        'meta_source': metadata.get('source', ''),
                        'meta_resolution': metadata.get('resolution', ''),
                        'meta_geographic_coverage': resolve_i18n(metadata.get('geographic_coverage', ''), lang),
                        'meta_license': metadata.get('license', ''),
                        'meta_frequency_of_update': resolve_i18n(metadata.get('frequency_of_update', ''), lang),
                        'meta_function': resolve_i18n(metadata.get('function', ''), lang),
                        'meta_overview': resolve_i18n(metadata.get('overview', ''), lang),
                        'meta_learn_more': metadata.get('learn_more', ''),
                    }
                    entry_counter += 1

                    handle_entry(product_code, defaults, stats)


def _load_products_format(json_data, stats, lang='en', ecmwf_token='', estation_product_ids=None, estation_url='', handle_entry=None):
    """
    Load from the flat products format (e.g. jrc_station_products.json).
    Each product has: category, product_id, descriptive_name, wms_getmap_url, resource_url.
    """
    if handle_entry is None:
        handle_entry = _upsert_entry
    server_url = json_data.get('ServerURL', 'localhost')
    # Build WMS base URL from server URL
    if not server_url.startswith('http'):
        wms_base_url = f"https://{server_url}/webservices"
    else:
        wms_base_url = server_url.rstrip('/') + '/webservices'

    cat_order_map = {}
    entry_counter = 0

    for product in json_data.get('products', []):
        product_id = product.get('product_id', '')
        if not product_id:
            stats['errors'].append(f"Skipping product without product_id: {product.get('descriptive_name', '?')}")
            continue

        # eStation filtering: skip products not available on the local instance
        if estation_product_ids is not None:
            if product_id not in estation_product_ids:
                stats['skipped_estation'] += 1
                continue

        category = product.get('category', 'Uncategorized')
        # Capitalize category title
        cat_title = category.capitalize()

        # Extract WMS layer name from wms_getmap_url (LAYERS= param) or use product_id
        layer_name = product_id
        wms_url_raw = product.get('wms_getmap_url', '')
        wms_url = wms_base_url
        if wms_url_raw:
            # Extract base URL (before query params)
            if '?' in wms_url_raw:
                base_part = wms_url_raw.split('?')[0]
                if not base_part.startswith('http'):
                    base_part = f"https://{base_part}"
                wms_url = base_part

            # Extract LAYERS param value if present
            import urllib.parse
            parsed = urllib.parse.urlparse(wms_url_raw if '://' in wms_url_raw else f"https://{wms_url_raw}")
            params = urllib.parse.parse_qs(parsed.query)
            if 'LAYERS' in params:
                layer_name = params['LAYERS'][0]

        # Substitute eStation URL with local instance
        wms_url = _substitute_estation_url(wms_url, estation_url)

        descriptive_name = product.get('descriptive_name', product_id)

        if cat_title not in cat_order_map:
            cat_order_map[cat_title] = len(cat_order_map)

        defaults = {
            'title': descriptive_name,
            'summary': descriptive_name,
            'category_title': cat_title,
            'category_icon': 'map',
            'subcategory_title': 'Observation',
            'category_order': cat_order_map[cat_title],
            'subcategory_order': 0,
            'entry_order': entry_counter,
            'layer_type': 'wms',
            'layer_name': layer_name,
            'wms_url': wms_url,
            'layer_title': descriptive_name,
            'multi_temporal': True,
            'origin': CatalogEntry.ORIGIN_CONFIG,
            'meta_source': 'JRC eStation',
            'meta_learn_more': product.get('resource_url', ''),
        }
        entry_counter += 1

        handle_entry(product_id, defaults, stats)


def _upsert_entry(product_code, defaults, stats, conflict_policy='overwrite'):
    """
    Create or update a CatalogEntry and update stats.

    Outcomes (tracked in stats):
      - created          : no row existed for this product_code
      - updated          : row existed, catalog content changed, applied
      - unchanged        : row existed, catalog content is byte-identical
      - conflict_skipped : row existed, catalog content changed, but the
                           provisioned Climweb Dataset has diverged from
                           its baseline AND conflict_policy='skip' — the
                           local edits win, the catalog change is held off.

    ``defaults['enabled']`` (when given) only applies to a new entry: on
    later loads the admin's selection is kept.
    """
    defaults = dict(defaults)
    enabled = defaults.pop('enabled', True)
    incoming_hash = compute_source_hash(defaults)

    try:
        entry = CatalogEntry.objects.get(product_code=product_code)
    except CatalogEntry.DoesNotExist:
        entry = None

    if entry is None:
        CatalogEntry.objects.create(
            product_code=product_code,
            source_hash=incoming_hash,
            enabled=enabled,
            **defaults,
        )
        stats['created'] += 1
        return

    if entry.source_hash == incoming_hash:
        stats['unchanged'] += 1
        return

    if conflict_policy == 'skip' and entry.dataset_id and entry.provisioned_hash:
        current = compute_provisioned_hash(entry.dataset_id)
        if current != entry.provisioned_hash:
            stats['conflict_skipped'] += 1
            return

    for field, value in defaults.items():
        setattr(entry, field, value)
    entry.source_hash = incoming_hash
    entry.save()
    stats['updated'] += 1


def sync_catalog_to_climweb():
    """
    Synchronize CatalogEntry state to Climweb DB.

    - pending_add entries: create Climweb objects and store dataset_id
    - pending_remove entries: delete Climweb Dataset (cascades) and clear dataset_id
    - synced entries:
        * verify Dataset still exists; orphan-clear if not
        * if source_hash advanced since last sync, re-provision (write-
          through of catalog updates)
        * otherwise, only sync the public flag (cheap drift check)
      raster_file is intentionally skipped from re-provision — wiping
      uploaded time-slot files just to update a title would be too
      destructive, so the drift is surfaced via a counter instead.

    Returns stats dict.
    """
    stats = {
        'added': 0,
        'removed': 0,
        'reprovisioned': 0,
        'raster_file_drift': 0,
        'orphans_cleared': 0,
        'already_synced': 0,
        'public_updated': 0,
        'errors': [],
    }

    entries = CatalogEntry.objects.all()

    for entry in entries:
        status = entry.status

        if status == CatalogEntry.STATUS_SYNCED:
            try:
                with transaction.atomic():
                    dataset = Dataset.objects.filter(id=entry.dataset_id).first()
                    if dataset is None:
                        entry.dataset_id = None
                        entry.provisioned_hash = ''
                        entry.provisioned_source_hash = ''
                        entry.save(update_fields=[
                            'dataset_id', 'provisioned_hash',
                            'provisioned_source_hash', 'updated_at',
                        ])
                        stats['orphans_cleared'] += 1
                        continue

                    # First-time baseline for entries that pre-date the
                    # provisioned_source_hash migration: any pre-migration
                    # drift is unrecoverable, but we want detection to work
                    # going forward.
                    if entry.source_hash and not entry.provisioned_source_hash:
                        entry.provisioned_source_hash = entry.source_hash
                        if not entry.provisioned_hash:
                            entry.provisioned_hash = compute_provisioned_hash(entry.dataset_id)
                        entry.save(update_fields=[
                            'provisioned_hash', 'provisioned_source_hash', 'updated_at',
                        ])
                        stats['already_synced'] += 1
                        continue

                    catalog_moved = (
                        entry.source_hash
                        and entry.provisioned_source_hash
                        and entry.source_hash != entry.provisioned_source_hash
                    )

                    if catalog_moved and entry.layer_type == CatalogEntry.LAYER_TYPE_RASTER_FILE:
                        # Re-provisioning would delete uploaded LayerRasterFile
                        # rows; surface the drift but leave Climweb alone.
                        stats['raster_file_drift'] += 1
                        stats['already_synced'] += 1
                    elif catalog_moved:
                        _reprovision_entry(entry, dataset)
                        entry.provisioned_hash = compute_provisioned_hash(entry.dataset_id)
                        entry.provisioned_source_hash = entry.source_hash
                        entry.save(update_fields=[
                            'provisioned_hash', 'provisioned_source_hash', 'updated_at',
                        ])
                        stats['reprovisioned'] += 1
                    else:
                        if dataset.public != entry.public:
                            dataset.public = entry.public
                            dataset.save(update_fields=['public'])
                            stats['public_updated'] += 1
                        stats['already_synced'] += 1
            except Exception as e:
                stats['errors'].append(f"Failed to reconcile '{entry.title}': {e}")
                logger.exception("Failed to reconcile catalog entry %s", entry.product_code)

        elif status == CatalogEntry.STATUS_PENDING_ADD:
            try:
                with transaction.atomic():
                    dataset_id = _provision_entry(entry)
                    entry.dataset_id = dataset_id
                    entry.provisioned_hash = compute_provisioned_hash(dataset_id)
                    entry.provisioned_source_hash = entry.source_hash
                    entry.save(update_fields=[
                        'dataset_id', 'provisioned_hash',
                        'provisioned_source_hash', 'updated_at',
                    ])
                stats['added'] += 1
            except Exception as e:
                stats['errors'].append(f"Failed to provision '{entry.title}': {e}")
                logger.exception("Failed to provision catalog entry %s", entry.product_code)

        elif status == CatalogEntry.STATUS_PENDING_REMOVE:
            try:
                with transaction.atomic():
                    _deprovision_entry(entry)
                    entry.dataset_id = None
                    entry.provisioned_hash = ''
                    entry.provisioned_source_hash = ''
                    entry.save(update_fields=[
                        'dataset_id', 'provisioned_hash',
                        'provisioned_source_hash', 'updated_at',
                    ])
                stats['removed'] += 1
            except Exception as e:
                stats['errors'].append(f"Failed to deprovision '{entry.title}': {e}")
                logger.exception("Failed to deprovision catalog entry %s", entry.product_code)

        # STATUS_DISABLED: nothing to do

    return stats


# ---------------------------------------------------------------------------
# Provisioning helpers
# ---------------------------------------------------------------------------


def _create_common_objects(entry):
    """
    Create the shared Climweb objects for any layer type:
    Category, SubCategory, Metadata, Dataset.
    Returns the new Dataset instance.
    """
    category, _ = Category.objects.get_or_create(
        title=entry.category_title,
        defaults={
            'icon': entry.category_icon,
            'active': True,
            'public': True,
        },
    )
    # Persist the JSON-driven position into Category.order (wagtail-adminsortable).
    # We update on every sync so admins re-loading the catalog get the order
    # reflected, but we don't touch icon/active/public to preserve manual edits.
    if category.order != entry.category_order:
        category.order = entry.category_order
        category.save(update_fields=['order'])

    subcategory, _ = SubCategory.objects.get_or_create(
        title=entry.subcategory_title,
        category=category,
        defaults={
            'active': True,
            'public': True,
        },
    )
    # SubCategory uses Orderable's ``sort_order`` (not AdminSortable's ``order``).
    if subcategory.sort_order != entry.subcategory_order:
        subcategory.sort_order = entry.subcategory_order
        subcategory.save(update_fields=['sort_order'])

    metadata = None
    if any([
        entry.meta_source, entry.meta_resolution, entry.meta_function,
        entry.meta_overview, entry.meta_geographic_coverage,
    ]):
        metadata = Metadata.objects.create(
            title=entry.meta_source or entry.title,
            function=entry.meta_function or None,
            resolution=entry.meta_resolution or None,
            geographic_coverage=entry.meta_geographic_coverage or None,
            source=entry.meta_source or None,
            license=entry.meta_license or None,
            frequency_of_update=entry.meta_frequency_of_update or None,
            overview=entry.meta_overview or None,
            learn_more=entry.meta_learn_more or None,
        )

    # raster_file datasets require a time dimension on every LayerRasterFile,
    # so the parent Dataset must always be multi_temporal.
    multi_temporal = True if entry.layer_type == CatalogEntry.LAYER_TYPE_RASTER_FILE else entry.multi_temporal

    dataset = Dataset.objects.create(
        title=entry.title,
        category=category,
        sub_category=subcategory,
        layer_type=entry.layer_type,
        metadata=metadata,
        published=True,
        public=entry.public,
        multi_temporal=multi_temporal,
        multi_layer=False,
        near_realtime=entry.near_realtime,
        can_clip=False,
        initial_visible=entry.initial_visible,
        auto_update_interval=entry.auto_update_interval,
        current_time_method=entry.current_time_method or DEFAULT_CURRENT_TIME_METHOD,
    )

    if entry.summary:
        dataset.summary = entry.summary
        dataset.save(update_fields=['summary'])

    return dataset


def _provision_entry(entry):
    """
    Create Climweb objects for a single CatalogEntry.
    Dispatches to a type-specific provisioner.
    Returns the new Dataset UUID.
    """
    dataset = _create_common_objects(entry)
    provisioner = _PROVISIONERS.get(entry.layer_type)
    if provisioner is None:
        raise ValueError(f"Unsupported layer type: {entry.layer_type}")
    provisioner(entry, dataset)
    return dataset.id


def _clear_layer_objects(dataset):
    """
    Delete the layer-type-specific objects attached to ``dataset`` so the
    matching provisioner can re-create them cleanly. Children of these
    layer objects (WmsRequestLayer, WmsRequestParam, …) cascade-delete.
    raster_file is deliberately not cleared — its uploaded files would
    be lost; ``sync_catalog_to_climweb`` skips raster_file re-provision
    for the same reason.
    """
    WmsLayer.objects.filter(dataset=dataset).delete()
    RasterTileLayer.objects.filter(dataset=dataset).delete()
    VectorTileLayer.objects.filter(dataset=dataset).delete()
    if RasterCOGLayer is not None:
        RasterCOGLayer.objects.filter(dataset=dataset).delete()
    if OpenMeteoLayer is not None:
        OpenMeteoLayer.objects.filter(dataset=dataset).delete()


def _reprovision_entry(entry, dataset):
    """
    Push the current CatalogEntry contents back onto an already-provisioned
    Climweb Dataset, preserving its UUID (so any external reference that
    points at this Dataset stays valid).

    Updates Category/SubCategory assignment (catalog can reshuffle these),
    Dataset scalar fields, Metadata (one-to-one), and replaces the
    layer-type-specific objects via the same provisioner used by the
    add path.
    """
    category, _ = Category.objects.get_or_create(
        title=entry.category_title,
        defaults={'icon': entry.category_icon, 'active': True, 'public': True},
    )
    if category.order != entry.category_order:
        category.order = entry.category_order
        category.save(update_fields=['order'])

    subcategory, _ = SubCategory.objects.get_or_create(
        title=entry.subcategory_title,
        category=category,
        defaults={'active': True, 'public': True},
    )
    if subcategory.sort_order != entry.subcategory_order:
        subcategory.sort_order = entry.subcategory_order
        subcategory.save(update_fields=['sort_order'])

    multi_temporal = (
        True
        if entry.layer_type == CatalogEntry.LAYER_TYPE_RASTER_FILE
        else entry.multi_temporal
    )
    dataset.title = entry.title
    dataset.category = category
    dataset.sub_category = subcategory
    dataset.layer_type = entry.layer_type
    dataset.public = entry.public
    dataset.multi_temporal = multi_temporal
    dataset.near_realtime = entry.near_realtime
    dataset.initial_visible = entry.initial_visible
    dataset.auto_update_interval = entry.auto_update_interval
    if entry.current_time_method:
        dataset.current_time_method = entry.current_time_method
    dataset.summary = entry.summary or ''
    dataset.save()

    has_metadata_fields = any([
        entry.meta_source, entry.meta_resolution, entry.meta_function,
        entry.meta_overview, entry.meta_geographic_coverage,
    ])
    if dataset.metadata:
        m = dataset.metadata
        m.title = entry.meta_source or entry.title
        m.function = entry.meta_function or None
        m.resolution = entry.meta_resolution or None
        m.geographic_coverage = entry.meta_geographic_coverage or None
        m.source = entry.meta_source or None
        m.license = entry.meta_license or None
        m.frequency_of_update = entry.meta_frequency_of_update or None
        m.overview = entry.meta_overview or None
        m.learn_more = entry.meta_learn_more or None
        m.save()
    elif has_metadata_fields:
        metadata = Metadata.objects.create(
            title=entry.meta_source or entry.title,
            function=entry.meta_function or None,
            resolution=entry.meta_resolution or None,
            geographic_coverage=entry.meta_geographic_coverage or None,
            source=entry.meta_source or None,
            license=entry.meta_license or None,
            frequency_of_update=entry.meta_frequency_of_update or None,
            overview=entry.meta_overview or None,
            learn_more=entry.meta_learn_more or None,
        )
        dataset.metadata = metadata
        dataset.save(update_fields=['metadata'])

    _clear_layer_objects(dataset)
    provisioner = _PROVISIONERS.get(entry.layer_type)
    if provisioner is None:
        raise ValueError(f"Unsupported layer type: {entry.layer_type}")
    provisioner(entry, dataset)


def _provision_wms(entry, dataset):
    """Create WmsLayer + WmsRequestLayer for a WMS catalog entry."""
    wms_layer = WmsLayer.objects.create(
        dataset=dataset,
        title=entry.layer_title or entry.title,
        base_url=entry.wms_url,
        version='1.3.0',
        width=256,
        height=256,
        transparent=True,
        srs='EPSG:3857',
        format='image/png',
        default=True,
        request_time_from_capabilities=True,
        legend_from_capabilities=entry.legend_from_capabilities,
        popup=entry.popup,
    )

    WmsRequestLayer.objects.create(
        layer=wms_layer,
        name=entry.layer_name,
    )

    # Add extra WMS query params if present
    if entry.extra_params_json and isinstance(entry.extra_params_json, dict):
        for param_name, param_value in entry.extra_params_json.items():
            WmsRequestParam.objects.create(
                layer=wms_layer,
                name=param_name,
                value=str(param_value),
            )


def _provision_raster_tile(entry, dataset):
    """Create a RasterTileLayer for an XYZ raster tile catalog entry."""
    kwargs = dict(
        dataset=dataset,
        title=entry.layer_title or entry.title,
        base_url=entry.tile_url,
        default=True,
    )

    if entry.legend_json:
        add_legend_kwargs(kwargs, entry.legend_json, RasterTileLayer,
                            lang=PluginSettings.load().language)

    RasterTileLayer.objects.create(**kwargs)


def _provision_vector_tile(entry, dataset):
    """Create a VectorTileLayer for an MVT vector tile catalog entry."""
    lang = PluginSettings.load().language
    kwargs = dict(
        dataset=dataset,
        title=entry.layer_title or entry.title,
        base_url=entry.tile_url,
        default=True,
        is_pmtiles=entry.is_pmtiles,
        use_render_layers_json=bool(entry.render_layers_json),
        render_layers_json=entry.render_layers_json,
    )

    popup_stream = _build_popup_stream_value(entry.popup_config_json, lang=lang)
    if popup_stream:
        kwargs['popup_config'] = popup_stream

    if entry.legend_json:
        add_legend_kwargs(kwargs, entry.legend_json, VectorTileLayer, lang=lang)

    VectorTileLayer.objects.create(**kwargs)


def _provision_raster_cog(entry, dataset):
    """Create a RasterCOGLayer + RasterStyle from catalog entry config."""
    if RasterCOGLayer is None:
        raise RuntimeError(
            "raster_cog layer type requires geomanager with the raster_cog model "
            "(branch 'cog'). Current geomanager build does not expose it."
        )
    style = _create_raster_style_from_config(
        entry.raster_style_json or {},
        name=entry.layer_title or entry.title,
        lang=PluginSettings.load().language,
    )
    RasterCOGLayer.objects.create(
        dataset=dataset,
        title=entry.layer_title or entry.title,
        default=True,
        url_template=entry.cog_url_template,
        time_start=entry.cog_time_start,
        time_end=entry.cog_time_end,
        time_step_value=entry.cog_time_step_value,
        time_step_unit=entry.cog_time_step_unit,
        date_format=entry.cog_date_format or None,
        style=style,
    )


def _provision_openmeteo(entry, dataset):
    """
    Create an OpenMeteoLayer from catalog entry config. The map viewer reads
    the latest run of the weather model and renders the variable with the
    Open-Meteo protocol, so there is no style or legend to set up.
    """
    if OpenMeteoLayer is None:
        raise RuntimeError(
            "openmeteo layer type requires geomanager with the OpenMeteoLayer model. "
            "Current geomanager build does not expose it."
        )
    kwargs = dict(
        dataset=dataset,
        title=entry.layer_title or entry.title,
        default=True,
        domain=entry.openmeteo_domain,
        variable=entry.openmeteo_variable,
    )
    # left out, GeoManager falls back to the public Open-Meteo bucket
    if entry.openmeteo_base_url:
        kwargs['base_url'] = entry.openmeteo_base_url
    if entry.openmeteo_date_format:
        kwargs['date_format'] = entry.openmeteo_date_format
    OpenMeteoLayer.objects.create(**kwargs)


_PROVISIONERS = {
    'wms': _provision_wms,
    'raster_tile': _provision_raster_tile,
    'vector_tile': _provision_vector_tile,
    'raster_cog': _provision_raster_cog,
    'openmeteo': _provision_openmeteo,
    **_PACKAGED_PROVISIONERS,  # adds 'raster_file' (provisioners/raster_file.py)
}


_VALID_RASTER_LEGEND_TYPES = (
    'basic', 'choropleth', 'choropleth_vertical', 'gradient', 'gradient_vertical',
)


_HEX_RE = re.compile(r'^#[0-9a-fA-F]+$')


def _normalize_hex_color(value, default='#ff0000'):
    """
    Normalize a hex color string to 6-digit ``#RRGGBB``.

    Accepts ``#RGB``, ``#RRGGBB``, ``#RRGGBBAA`` (alpha stripped with a warning).
    Returns ``default`` if the value is empty/invalid.
    """
    if not value or not isinstance(value, str):
        return default
    if not _HEX_RE.match(value):
        logger.warning("Invalid hex color %r — using %s", value, default)
        return default
    body = value[1:]
    if len(body) == 3:
        return '#' + ''.join(c * 2 for c in body)
    if len(body) == 6:
        return value
    if len(body) == 8:
        logger.info("Stripping alpha channel from color %s → #%s", value, body[:6])
        return '#' + body[:6]
    logger.warning("Unexpected hex length for %r — using %s", value, default)
    return default


def _create_raster_style_from_config(config, name='', lang='en'):
    """
    Create a RasterStyle from an explicit JSON config dict.

    Recognized keys (all optional; defaults applied):
      name, unit, min, max, steps, palette, interpolate, legend_type,
      use_custom_colors, custom_colors, custom_color_for_rest.

    When ``use_custom_colors`` is true (or ``custom_colors`` is non-empty),
    a ColorValue is created for each entry in ``custom_colors``
    (keys: threshold, color, label?, show_on_legend?). ``label`` may be
    a multilingual dict ({en, fr, ...}) — resolved via the configured ``lang``.
    ``custom_color_for_rest`` is the fallback color for values outside
    the defined thresholds.
    """
    cfg = config or {}
    legend_type = cfg.get('legend_type', 'choropleth_vertical')
    if legend_type not in _VALID_RASTER_LEGEND_TYPES:
        legend_type = 'choropleth_vertical'

    custom_colors = cfg.get('custom_colors') or []
    use_custom_colors = bool(cfg.get('use_custom_colors') or custom_colors)

    style = RasterStyle.objects.create(
        name=(cfg.get('name') or name or 'raster')[:256],
        unit=resolve_i18n(cfg.get('unit'), lang) or '',
        min=int(cfg.get('min', 0)),
        max=int(cfg.get('max', 100)),
        steps=int(cfg.get('steps', 9)),
        palette=cfg.get('palette') or DEFAULT_RASTER_PALETTE,
        interpolate=bool(cfg.get('interpolate', False)),
        legend_type=legend_type,
        use_custom_colors=use_custom_colors,
        custom_color_for_rest=_normalize_hex_color(cfg.get('custom_color_for_rest'), default='#ff0000'),
    )

    for item in custom_colors:
        ColorValue.objects.create(
            layer=style,
            threshold=float(item['threshold']),
            color=_normalize_hex_color(item.get('color'), default='#000000'),
            show_on_legend=bool(item.get('show_on_legend', True)),
            label=resolve_i18n(item.get('label'), lang) or None,
        )

    return style


def _build_popup_stream_value(popup_config, lang='en'):
    """
    Build a StreamField value for ``VectorTileLayer.popup_config`` from the
    catalog's ``popup_config_json`` list.

    Each input item: ``{"data_key", "label", "data_type"}``.
    ``label`` may be an i18n dict; it's resolved with ``resolve_i18n``.
    """
    if not popup_config or not isinstance(popup_config, list):
        return None

    blocks = []
    for item in popup_config:
        data_key = (item.get('data_key') or '').strip()
        if not data_key:
            continue
        label = resolve_i18n(item.get('label'), lang) or data_key
        data_type = item.get('data_type') or 'string'
        if data_type not in ('string', 'number'):
            data_type = 'string'
        blocks.append({
            'type': 'popup_fields',
            'id': str(uuid.uuid4()),
            'value': {
                'data_key': data_key,
                'label': label,
                'data_type': data_type,
            },
        })
    return blocks or None


# ---------------------------------------------------------------------------
# Deprovision
# ---------------------------------------------------------------------------


def _deprovision_entry(entry):
    """
    Delete the Climweb Dataset associated with a CatalogEntry.
    Cascading deletes handle all layer types (WmsLayer, RasterTileLayer,
    VectorTileLayer, RasterFileLayer, VectorFileLayer and their children).
    """
    if entry.dataset_id:
        Dataset.objects.filter(id=entry.dataset_id).delete()


def _try_delete(obj):
    """
    Attempt to delete a single taxonomy object inside a savepoint.
    Return True on success, False if the row is still referenced from
    outside the plugin (PROTECT/RESTRICT FKs or DB-level FK constraints
    from other apps such as ``cap_capgeomanagersettings``). The savepoint
    ensures a failure here does not poison the surrounding transaction.
    """
    try:
        with transaction.atomic():
            obj.delete()
    except (ProtectedError, RestrictedError, IntegrityError) as exc:
        logger.info(
            "Skipping delete of %s id=%s — still referenced: %s",
            obj._meta.label, obj.pk, exc,
        )
        return False
    return True


def _sweep_empty_taxonomy():
    """
    Delete SubCategories that no longer reference any Dataset, then
    Categories that no longer reference any Dataset or SubCategory.

    Emptiness is determined against the *current* Dataset / SubCategory
    state — so anything still pointed to by a non-plugin Dataset stays.
    PROTECT FKs on Dataset.category and Dataset.sub_category give Django
    a built-in safety net: the exclude() filter is the primary guard,
    PROTECT is the belt-and-suspenders.

    Rows still referenced by *other* apps (e.g. CAP's
    ``cap_capgeomanagersettings``) are silently skipped rather than
    aborting the whole clear operation.

    Returns (subcategories_deleted, categories_deleted).
    """
    subcat_ids_with_datasets = (
        Dataset.objects
        .exclude(sub_category=None)
        .values_list('sub_category_id', flat=True)
        .distinct()
    )
    empty_subcats = list(
        SubCategory.objects.exclude(id__in=list(subcat_ids_with_datasets))
    )
    subcats_deleted = sum(1 for sc in empty_subcats if _try_delete(sc))

    cat_ids_with_datasets = (
        Dataset.objects
        .exclude(category=None)
        .values_list('category_id', flat=True)
        .distinct()
    )
    cat_ids_with_subcats = (
        SubCategory.objects
        .values_list('category_id', flat=True)
        .distinct()
    )
    cat_ids_in_use = set(cat_ids_with_datasets) | set(cat_ids_with_subcats)
    empty_cats = list(Category.objects.exclude(id__in=cat_ids_in_use))
    cats_deleted = sum(1 for c in empty_cats if _try_delete(c))

    return subcats_deleted, cats_deleted


def clear_provisioned_datasets():
    """
    Delete every Climweb Dataset that this plugin provisioned (i.e. every
    Dataset whose UUID is referenced by some ``CatalogEntry.dataset_id``)
    together with its dedicated Metadata, then garbage-collect any
    SubCategories and Categories left empty as a result. Categories and
    SubCategories still referenced by external (non-plugin) Datasets
    stay untouched.

    CatalogEntry rows themselves are preserved; their ``dataset_id`` and
    provisioning hashes are cleared, so each entry goes back to
    ``pending_add`` and can be re-provisioned by the next sync.
    """
    entries_qs = CatalogEntry.objects.exclude(dataset_id=None)
    dataset_ids = list(entries_qs.values_list('dataset_id', flat=True))

    target_datasets = Dataset.objects.filter(id__in=dataset_ids)
    datasets_count = target_datasets.count()
    metadata_ids = list(
        target_datasets
        .exclude(metadata=None)
        .values_list('metadata_id', flat=True)
    )

    # Delete Datasets first — cascade takes care of WmsLayer / RasterTileLayer
    # / etc. and their children. Metadata is FK'd FROM Dataset so it gets
    # orphaned, not cascade-deleted; clean it up explicitly below.
    target_datasets.delete()

    metadata_result = Metadata.objects.filter(id__in=metadata_ids).delete()
    metadata_deleted = metadata_result[0] if metadata_result else 0

    subcats_deleted, cats_deleted = _sweep_empty_taxonomy()

    entries_reset = entries_qs.update(
        dataset_id=None,
        provisioned_hash='',
        provisioned_source_hash='',
        updated_at=timezone.now(),
    )

    return {
        'datasets_deleted': datasets_count,
        'metadata_deleted': metadata_deleted,
        'subcategories_deleted': subcats_deleted,
        'categories_deleted': cats_deleted,
        'entries_reset': entries_reset,
    }


def get_catalog_tree():
    """
    Return the full catalog as a nested dict for the tree UI.
    Structure: categories > subcategories > entries
    """
    entries = CatalogEntry.objects.all()
    tree = {}

    for entry in entries:
        cat = entry.category_title
        subcat = entry.subcategory_title

        if cat not in tree:
            tree[cat] = {
                'title': cat,
                'icon': entry.category_icon,
                'subcategories': {},
            }

        subcats = tree[cat]['subcategories']
        if subcat not in subcats:
            subcats[subcat] = {
                'title': subcat,
                'entries': [],
            }

        subcats[subcat]['entries'].append({
            'id': str(entry.id),
            'product_code': entry.product_code,
            'title': entry.title,
            'summary': entry.summary,
            'layer_type': entry.layer_type,
            'layer_name': entry.layer_name,
            'layer_title': entry.layer_title,
            'wms_url': entry.wms_url,
            'tile_url': entry.tile_url,
            'is_pmtiles': entry.is_pmtiles,
            'file_url': entry.file_url,
            'openmeteo_base_url': entry.openmeteo_base_url,
            'openmeteo_domain': entry.openmeteo_domain,
            'openmeteo_variable': entry.openmeteo_variable,
            'render_layers_json': entry.render_layers_json,
            'popup_config_json': entry.popup_config_json,
            'popup': entry.popup,
            'legend_from_capabilities': entry.legend_from_capabilities,
            'extra_params_json': entry.extra_params_json,
            'legend_json': entry.legend_json,
            'multi_temporal': entry.multi_temporal,
            'near_realtime': entry.near_realtime,
            'initial_visible': entry.initial_visible,
            'auto_update_interval': entry.auto_update_interval,
            'enabled': entry.enabled,
            'status': entry.status,
            'origin': entry.origin,
            'meta_source': entry.meta_source,
            'meta_resolution': entry.meta_resolution,
            'meta_geographic_coverage': entry.meta_geographic_coverage,
            'meta_license': entry.meta_license,
            'meta_frequency_of_update': entry.meta_frequency_of_update,
            'meta_function': entry.meta_function,
            'meta_overview': entry.meta_overview,
            'meta_learn_more': entry.meta_learn_more,
        })

    # Convert to list, preserving insertion order (driven by DB ordering)
    result = []
    for cat in tree.values():
        subcats_list = list(cat['subcategories'].values())
        result.append({
            'title': cat['title'],
            'icon': cat['icon'],
            'subcategories': subcats_list,
        })

    return result
