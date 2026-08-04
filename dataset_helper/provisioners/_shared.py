"""Helpers shared across provisioner modules."""
import logging
import os
import tempfile
import urllib.request
import uuid
from urllib.parse import quote

from ..models import PluginSettings

logger = logging.getLogger(__name__)


DEFAULT_RASTER_PALETTE = (
    '#2166ac,#4393c3,#92c5de,#d1e5f0,#f7f7f7,#fddbc7,#f4a582,#d6604d,#b2182b'
)

VALID_LEGEND_TYPES = ('basic', 'choropleth', 'gradient')


def resolve_i18n(value, lang='en'):
    """
    Resolve a multilingual value. If ``value`` is a dict with language keys,
    return the string for ``lang`` (fallback to ``en``, then first available).
    If it is already a string, return it as-is.
    """
    if isinstance(value, dict):
        return value.get(lang) or value.get('en') or next(iter(value.values()), '')
    return value or ''


def add_legend_kwargs(kwargs, legend_config, model_class, lang='en'):
    """
    Add legend fields to a ``Model.objects.create()`` kwargs dict.

    ``legend_config`` shape::

        {"type": "basic|choropleth|gradient",
         "items": [{"name": <str|i18n dict>, "color": "#rrggbb"}, ...]}

    Builds an ``InlineLegendBlock``-compatible StreamField value (a Python
    list, not a JSON string) and stores it under ``kwargs['legend']`` so
    the legend is set atomically in the same ``create()`` call. Sets
    ``use_custom_legend=True`` when the model exposes that flag.

    Unknown legend types (e.g. ``categorical``) are normalized to ``basic``,
    the closest native rendering. Models without a ``legend`` field are
    skipped with a warning.
    """
    if not hasattr(model_class, 'legend'):
        logger.warning(
            "Model %s does not have a legend field — legend config stored "
            "in catalog entry but not applied to the Climweb layer.",
            model_class.__name__,
        )
        return

    legend_type = legend_config.get('type', 'basic')
    if legend_type not in VALID_LEGEND_TYPES:
        logger.info("Unknown legend type '%s' — falling back to 'basic'.", legend_type)
        legend_type = 'basic'

    items = legend_config.get('items', [])
    stream_items = [
        {
            'color': item.get('color', ''),
            'value': resolve_i18n(item.get('name'), lang),
        }
        for item in items
    ]

    kwargs['legend'] = [{
        'type': 'legend',
        'id': str(uuid.uuid4()),
        'value': {
            'type': legend_type,
            'items': stream_items,
        },
    }]

    if hasattr(model_class, 'use_custom_legend'):
        kwargs['use_custom_legend'] = True


def resolve_file_url(url_template):
    """
    Replace placeholders in a file URL with values from PluginSettings.
    Supported placeholders:
      ``{country_alpha3}`` / ``{COUNTRY_ALPHA3}`` — ISO 3166-1 alpha-3
      ``{country_alpha2}`` / ``{COUNTRY_ALPHA2}`` — ISO 3166-1 alpha-2
      ``{country_name}``   / ``{COUNTRY_NAME}``   — Nominatim display_name
    """
    settings = PluginSettings.load()
    url = url_template
    if settings.country_alpha3:
        url = url.replace('{country_alpha3}', settings.country_alpha3.lower())
        url = url.replace('{COUNTRY_ALPHA3}', settings.country_alpha3.upper())
    if settings.country_alpha2:
        url = url.replace('{country_alpha2}', settings.country_alpha2.lower())
        url = url.replace('{COUNTRY_ALPHA2}', settings.country_alpha2.upper())
    if settings.country_name:
        # Country name often contains spaces / accents — URL-encode so the
        # substituted URL stays valid (urllib rejects raw spaces, etc.).
        url = url.replace('{country_name}', quote(settings.country_name, safe=''))
        url = url.replace('{COUNTRY_NAME}', quote(settings.country_name.upper(), safe=''))
    return url


def download_file(url, suffix='.tif', bearer=None):
    """
    Download a URL to a temporary file. Returns the temp file path.
    Caller is responsible for cleanup.

    ``bearer``: optional token sent as ``Authorization: Bearer <token>`` for
    APIs that require auth (kept out of the URL so it never lands in logs).
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        headers = {'User-Agent': 'ClimwebDatasetHelper/1.0'}
        if bearer:
            headers['Authorization'] = f'Bearer {bearer}'
        req = urllib.request.Request(url, headers=headers)
        logger.info(
            "##### url '%s': bearer %s",
            url, bearer
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(tmp.name, 'wb') as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    logger.info("##### CHUNK %s",chunk)

        return tmp.name

    except Exception:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise
