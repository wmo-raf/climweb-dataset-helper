"""
Administrative boundaries importer (OCHA / HDX COD-AB).

This feature is **independent of the WMS layer catalog**. It bootstraps the
Climweb ``admin_boundaries`` layer served by the companion app
``adminboundarymanager`` (https://github.com/erick-otenyo/adm-boundary-manager),
which stores every admin unit in a single ``AdminBoundary`` table and serves it
as MVT vector tiles at ``/api/admin-boundary/tiles/{z}/{x}/{y}``.

Workflow automated here (mirrors the manual boundary-manager UI, source = OCHA):

  1. Resolve the country from :class:`PluginSettings` (ISO alpha-2 / alpha-3).
  2. Resolve the OCHA COD-AB shapefile ZIP for that country via the HDX CKAN
     API (``package_show?id=cod-ab-{iso3}``) — no URL is hard-coded.
  3. Download the global ``*.shp.zip`` (it bundles one shapefile per admin level).
  4. Extract it and discover the per-level shapefiles (adm0, adm1, adm2, …).
  5. Per level: normalize the attribute column names to the schema the
     COD-AB loader expects (``ADM{n}_EN`` / ``ADM{n}_FR`` + ``ADM{n}_PCODE``),
     force ``ADM0_PCODE`` to the configured country code so the boundary
     manager's country signals don't purge the rows, reproject to EPSG:4326.
  6. Re-ZIP each level and load it via ``load_cod_abs_boundary`` (in-process).

All heavy dependencies (``geopandas`` and the ``adminboundarymanager`` app) live
in the Climweb container, so they are imported lazily and treated as optional —
the plugin still loads without them and the endpoints return a clear error.
"""
import glob
import json as json_module
import logging
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile

from django.db.models import Count, Q

from .models import PluginSettings

logger = logging.getLogger(__name__)


# Source identifier of the OCHA Common Operational Datasets in the boundary
# manager (AdminBoundarySettings.data_source choice).
SOURCE_CODABS = 'codabs'
SOURCE_LABEL = 'OCHA Administrative Boundary Common Operational Datasets (COD-AB)'

# HDX (CKAN) action API. COD-AB datasets follow the slug ``cod-ab-{iso3}``.
HDX_PACKAGE_SHOW_URL = 'https://data.humdata.org/api/3/action/package_show?id=cod-ab-{iso3}'

# COD-AB only ships English and French attribute columns.
_SUPPORTED_LANG_SUFFIXES = ('EN', 'FR')

# Highest admin level the boundary manager understands.
MAX_LEVEL = 4


class BoundaryImportError(Exception):
    """Raised for any recoverable failure in the boundary import pipeline."""


def _download(url, suffix='.zip', timeout=300):
    """
    Stream ``url`` to a temporary file and return its path. Boundary archives
    can be tens of MB, so this streams in chunks (without per-chunk logging) and
    uses a generous timeout. The caller owns the returned file.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ClimwebDatasetHelper/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp.name, 'wb') as f:
            shutil.copyfileobj(resp, f, length=1 << 16)
        return tmp.name
    except Exception:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise


# ---------------------------------------------------------------------------
# Optional-dependency guards
# ---------------------------------------------------------------------------


def _boundary_manager_available():
    """
    Return ``(available: bool, error: str)``. ``available`` is True only when
    both the boundary-manager app and geopandas can be imported.
    """
    try:
        import geopandas  # noqa: F401
    except ImportError as e:
        return False, f"geopandas is not installed in this environment: {e}"
    try:
        import adminboundarymanager  # noqa: F401
    except ImportError as e:
        return False, (
            "The 'adminboundarymanager' app (adm-boundary-manager) is not "
            f"installed in this Climweb instance: {e}"
        )
    return True, ''


def _require_boundary_manager():
    """Raise :class:`BoundaryImportError` if the runtime deps are missing."""
    available, error = _boundary_manager_available()
    if not available:
        raise BoundaryImportError(error)


# ---------------------------------------------------------------------------
# Country / language helpers
# ---------------------------------------------------------------------------


def _lang_suffix(language):
    """Map a PluginSettings language to a COD-AB column suffix (EN/FR)."""
    return 'FR' if (language or '').lower() == 'fr' else 'EN'


def _country_codes(settings=None):
    """Return ``(iso2_upper, iso3_upper)`` from settings; '' when unset."""
    settings = settings or PluginSettings.load()
    iso2 = (settings.country_alpha2 or '').strip().upper()
    iso3 = (settings.country_alpha3 or '').strip().upper()
    return iso2, iso3


def _country_object(iso2):
    """
    Build the ``django_countries`` Country object the COD-AB loader expects.
    The loader reads ``.code`` (ISO-2) and ``.alpha3`` (ISO-3) off it.
    """
    from django_countries.fields import Country as DjangoCountry
    return DjangoCountry(code=iso2.upper())


def register_country(iso2):
    """
    Ensure the country is registered in ``AdminBoundarySettings.countries``.

    The boundary manager's ``Country`` post-save/post-delete signals purge any
    ``AdminBoundary`` row whose ``gid_0`` is not in the configured country set,
    so the country MUST be registered before (and is idempotent on re-import).
    """
    from wagtail.models import Site
    from adminboundarymanager.models import AdminBoundarySettings, Country

    site = Site.objects.filter(is_default_site=True).first() or Site.objects.first()
    if site is None:
        raise BoundaryImportError("No Wagtail Site configured; cannot resolve AdminBoundarySettings.")

    abm_settings = AdminBoundarySettings.for_site(site)
    code = iso2.upper()
    if abm_settings.countries.filter(country=code).exists():
        return False
    abm_settings.countries.add(Country(country=code))
    abm_settings.save()
    return True


# ---------------------------------------------------------------------------
# HDX CKAN URL resolution
# ---------------------------------------------------------------------------


def resolve_codab_shp_url(iso3):
    """
    Resolve the OCHA COD-AB shapefile ZIP download URL for ``iso3`` via the HDX
    CKAN ``package_show`` API. Returns ``(download_url, resource_name)``.

    Raises :class:`BoundaryImportError` if the dataset or a shapefile resource
    cannot be found.
    """
    iso3 = (iso3 or '').strip().lower()
    if not iso3:
        raise BoundaryImportError("Country ISO alpha-3 code is not set in plugin settings.")

    api_url = HDX_PACKAGE_SHOW_URL.format(iso3=iso3)
    try:
        req = urllib.request.Request(api_url, headers={'Accept': 'application/json',
                                                       'User-Agent': 'ClimwebDatasetHelper/1.0'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json_module.loads(resp.read().decode('utf-8'))
    except Exception as e:
        raise BoundaryImportError(
            f"Failed to query HDX for COD-AB dataset 'cod-ab-{iso3}': {e}"
        )

    if not payload.get('success') or not payload.get('result'):
        raise BoundaryImportError(
            f"HDX has no COD-AB dataset 'cod-ab-{iso3}' for this country."
        )

    resources = payload['result'].get('resources') or []
    resource = _pick_shp_resource(resources)
    if resource is None:
        raise BoundaryImportError(
            f"No shapefile (.shp.zip) resource found in HDX dataset 'cod-ab-{iso3}'."
        )

    url = (resource.get('download_url') or resource.get('url') or '').strip()
    if not url:
        raise BoundaryImportError(
            f"The COD-AB shapefile resource for '{iso3}' has no download URL."
        )
    return url, resource.get('name') or os.path.basename(url)


def _pick_shp_resource(resources):
    """
    Choose the best shapefile-ZIP resource from a CKAN resource list.

    Prefer a single combined archive (all admin levels in one ZIP) over a
    per-level one; among combined candidates, prefer the most 'authoritative'
    name (``admin_boundaries`` / ``adm_all``).
    """
    candidates = []
    for r in resources:
        url = (r.get('download_url') or r.get('url') or '').lower()
        fmt = (r.get('format') or '').upper()
        is_shp_zip = url.endswith('.shp.zip') or (
            fmt in ('SHP', 'SHAPEFILE', 'ZIPPED SHAPEFILE') and url.endswith('.zip')
        )
        if is_shp_zip:
            candidates.append(r)

    if not candidates:
        return None

    def score(r):
        name = ((r.get('name') or '') + ' ' + (r.get('url') or '')).lower()
        s = 0
        if 'admin_boundaries' in name:
            s += 5
        if 'adm_all' in name or 'admall' in name:
            s += 4
        if 'adm' in name:
            s += 1
        # Penalize single-level archives (e.g. *_adm2_*.shp.zip): we want the
        # combined file that holds every level.
        if re.search(r'adm(?:bnda[_-]?)?adm?\d\b', name) or re.search(r'_adm\d[_.-]', name):
            s -= 3
        return s

    candidates.sort(key=score, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# ZIP extraction + per-level shapefile discovery
# ---------------------------------------------------------------------------


def _extract_zip(zip_path, out_dir):
    """Extract ``zip_path`` into ``out_dir``, skipping ``__MACOSX`` cruft."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            if member.startswith('__MACOSX/') or os.path.basename(member).startswith('._'):
                continue
            zf.extract(member, out_dir)


def discover_level_shapefiles(root):
    """
    Walk ``root`` for shapefiles and return ``{level: shp_path}``.

    COD-AB archives use a few naming conventions for the polygon area files:
    ``*_admbnda_adm{n}_*.shp`` (OCHA itos export) and ``*_admin{n}.shp`` /
    ``*_adm{n}_*.shp`` (HDX combined export). Line (``adminlines`` /
    ``admbndl``), point (``adminpoints`` / ``admbndp``) and capital
    (``admincapitals``) layers are skipped — only polygon levels are loaded.
    When several files match the same level, the one whose name contains
    ``admbnda`` wins.
    """
    shp_paths = glob.glob(os.path.join(root, '**', '*.shp'), recursive=True)
    levels = {}
    for shp in shp_paths:
        base = os.path.basename(shp).lower()
        if any(tok in base for tok in (
            'admbndl', 'admbndp', 'adminline', 'adminpoint', 'admincapital',
            'lines', 'points', 'capital',
        )):
            continue  # line / point / capital boundary layers
        level = _level_from_filename(base)
        if level is None:
            continue
        is_area = 'admbnda' in base
        if level not in levels:
            levels[level] = (shp, is_area)
        elif is_area and not levels[level][1]:
            levels[level] = (shp, is_area)
    return {lvl: path for lvl, (path, _area) in levels.items()}


def _level_from_filename(base):
    """Extract the admin level (int 0..MAX_LEVEL) from a shapefile basename."""
    # Order matters: try the most specific tokens first. ``admin(\d)`` covers
    # the HDX combined export (``bfa_admin0.shp``); ``adm(\d)`` is the fallback.
    for pattern in (r'admbnda[_-]?adm?(\d)', r'admin(\d)', r'_adm(\d)[_.-]', r'adm(\d)'):
        m = re.search(pattern, base)
        if m:
            level = int(m.group(1))
            if 0 <= level <= MAX_LEVEL:
                return level
    return None


# ---------------------------------------------------------------------------
# Column normalization
# ---------------------------------------------------------------------------


def _find_name_col(columns, n, lang_suffix):
    """
    Find the source column holding the admin name for level ``n``.

    Handles both the ``ADM{n}_EN`` / ``ADM{n}_FR`` convention and the HDX itos
    convention where the primary name lives in ``adm{n}_name`` (with
    ``adm{n}_name1/2/3`` holding other-language variants — those are ignored).
    """
    upper = {c.upper(): c for c in columns}
    for cand in (f'ADM{n}_{lang_suffix}', f'ADM{n}_EN', f'ADM{n}_FR',
                 f'ADM{n}_NAME', f'ADM{n}NAME', f'ADM{n}_NM', f'ADM{n}NM'):
        if cand in upper:
            return upper[cand]
    # Anchored so we match ADM{n}_NAME but not ADM{n}_NAME1 / ADM{n}_NAME_ etc.
    pat = re.compile(rf'^ADM{n}_?(NAME|NM|EN|FR)$')
    for up, original in upper.items():
        if pat.match(up) and 'PCOD' not in up:
            return original
    return None


def _find_pcode_col(columns, n):
    """Find the source column holding the P-code for level ``n``."""
    upper = {c.upper(): c for c in columns}
    for cand in (f'ADM{n}_PCODE', f'ADM{n}_PCOD', f'ADM{n}PCODE', f'ADM{n}PCOD'):
        if cand in upper:
            return upper[cand]
    pat = re.compile(rf'^ADM{n}.*PCOD')
    for up, original in upper.items():
        if pat.match(up):
            return original
    return None


def _normalize_level_shapefile(src_shp, level, lang_suffix, iso2):
    """
    Read ``src_shp`` with geopandas, rename its attribute columns to the
    canonical COD-AB schema for ``level`` (``ADM{0..level}_{lang}`` +
    ``ADM{0..level}_PCODE``), force ``ADM0_PCODE`` to the country code, reproject
    to EPSG:4326, and write a fresh shapefile.

    Returns ``(out_dir, out_shp_path)``. The caller must delete ``out_dir``.
    """
    import geopandas as gpd

    gdf = gpd.read_file(src_shp)
    geom_name = gdf.geometry.name

    rename = {}
    for n in range(level + 1):
        target_name = f'ADM{n}_{lang_suffix}'
        target_pcode = f'ADM{n}_PCODE'
        src_name = _find_name_col(gdf.columns, n, lang_suffix)
        src_pcode = _find_pcode_col(gdf.columns, n)
        if src_name and src_name != target_name:
            rename[src_name] = target_name
        if src_pcode and src_pcode != target_pcode:
            rename[src_pcode] = target_pcode
    if rename:
        gdf = gdf.rename(columns=rename)

    # Guarantee every required column exists (the loader raises otherwise).
    for n in range(level + 1):
        if f'ADM{n}_{lang_suffix}' not in gdf.columns:
            gdf[f'ADM{n}_{lang_suffix}'] = ''
        if f'ADM{n}_PCODE' not in gdf.columns:
            gdf[f'ADM{n}_PCODE'] = ''

    # gid_0 in the boundary manager must equal the registered country code, or
    # the Country signals purge the rows. COD-AB ADM0_PCODE is normally the
    # ISO-2 already; force it to be safe.
    gdf['ADM0_PCODE'] = iso2.upper()

    # The AdminBoundary geometry column is MultiPolygon SRID 4326.
    try:
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
    except Exception as e:
        logger.warning("Could not reproject level %s to EPSG:4326: %s", level, e)

    if gdf.geometry.name != geom_name:
        gdf = gdf.set_geometry(gdf.geometry.name)

    out_dir = tempfile.mkdtemp(prefix=f'adm{level}_')
    out_shp = os.path.join(out_dir, f'adm{level}.shp')
    gdf.to_file(out_shp, driver='ESRI Shapefile')
    return out_dir, out_shp


def _zip_shapefile(shp_path):
    """
    Bundle a shapefile and all its sidecars (.shx/.dbf/.prj/.cpg/…) sharing the
    same basename into a single ``.zip``. Returns the ZIP path (in the same
    directory as ``shp_path``).
    """
    base = os.path.splitext(shp_path)[0]
    zip_path = base + '.shp.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for sidecar in glob.glob(base + '.*'):
            if sidecar.endswith('.shp.zip'):
                continue
            zf.write(sidecar, os.path.basename(sidecar))
    return zip_path


# ---------------------------------------------------------------------------
# AdminBoundary queries
# ---------------------------------------------------------------------------


def _country_filter(iso2, iso3):
    """Q filter matching AdminBoundary rows for the configured country."""
    codes = [c for c in (iso2.upper(), iso3.upper()) if c]
    return Q(gid_0__in=codes)


def _count_loaded(iso2, iso3, level):
    from adminboundarymanager.models import AdminBoundary
    return AdminBoundary.objects.filter(_country_filter(iso2, iso3), level=level).count()


# ---------------------------------------------------------------------------
# Tiles URL
# ---------------------------------------------------------------------------


def tiles_url_template():
    """Return the MVT tiles URL template for the admin boundaries layer."""
    try:
        from django.urls import reverse
        url = reverse('admin_boundary_tiles', args=[0, 0, 0])
        return url.replace('/0/0/0', '/{z}/{x}/{y}')
    except Exception:
        return '/api/admin-boundary/tiles/{z}/{x}/{y}'


# ---------------------------------------------------------------------------
# Public API: status / import / clear
# ---------------------------------------------------------------------------


def get_boundaries_status():
    """
    Return the current state of the admin-boundaries feature: availability,
    configured country/source, per-level feature counts already in the DB, and
    the MVT tiles URL template. Never raises — failures are reported inline.
    """
    settings = PluginSettings.load()
    iso2, iso3 = _country_codes(settings)
    available, error = _boundary_manager_available()

    status = {
        'available': available,
        'error': error,
        'source': SOURCE_CODABS,
        'source_label': SOURCE_LABEL,
        'lang_suffix': _lang_suffix(settings.language),
        'country': {
            'alpha2': iso2,
            'alpha3': iso3,
            'name': settings.country_name or '',
            'bbox': settings.country_bbox,
        },
        'tiles_url_template': tiles_url_template(),
        'levels': [],
        'total_features': 0,
    }

    if not available or not (iso2 or iso3):
        return status

    try:
        from adminboundarymanager.models import AdminBoundary
        rows = (
            AdminBoundary.objects
            .filter(_country_filter(iso2, iso3))
            .values('level')
            .annotate(features=Count('id'))
            .order_by('level')
        )
        levels = [{'level': r['level'], 'features': r['features']} for r in rows]
        status['levels'] = levels
        status['total_features'] = sum(r['features'] for r in levels)
    except Exception as e:
        logger.exception("Failed to read AdminBoundary counts")
        status['error'] = f"Could not read AdminBoundary table: {e}"

    return status


def import_admin_boundaries():
    """
    Run the full OCHA COD-AB import pipeline for the configured country.

    Returns a stats dict ``{source_url, resource, lang_suffix, levels: [...]}``
    where each level entry is ``{level, status, features?|message?}``.
    Raises :class:`BoundaryImportError` for setup failures (missing deps,
    unconfigured country, dataset not found, no shapefiles in the archive).
    """
    _require_boundary_manager()

    settings = PluginSettings.load()
    iso2, iso3 = _country_codes(settings)
    if not iso2 or not iso3:
        raise BoundaryImportError(
            "Country is not configured. Set the country (ISO alpha-2 and alpha-3) "
            "in the plugin settings before importing boundaries."
        )

    lang_suffix = _lang_suffix(settings.language)
    source_url, resource_name = resolve_codab_shp_url(iso3)

    from adminboundarymanager.loaders import load_cod_abs_boundary

    zip_path = _download(source_url, suffix='.shp.zip')
    extract_dir = tempfile.mkdtemp(prefix='codab_')
    try:
        _extract_zip(zip_path, extract_dir)
        level_shps = discover_level_shapefiles(extract_dir)
        if not level_shps:
            raise BoundaryImportError(
                "No admin-level shapefiles (adm0/adm1/…) were found in the "
                "downloaded COD-AB archive."
            )

        # Register the country first so the boundary-manager signals keep the
        # rows we are about to insert.
        register_country(iso2)
        country_obj = _country_object(iso2)

        results = []
        for level in sorted(level_shps):
            src_shp = level_shps[level]
            try:
                norm_dir, norm_shp = _normalize_level_shapefile(src_shp, level, lang_suffix, iso2)
            except Exception as e:
                logger.exception("Failed to normalize level %s", level)
                results.append({'level': level, 'status': 'error',
                                'message': f"normalize failed: {e}"})
                continue
            try:
                level_zip = _zip_shapefile(norm_shp)
                load_cod_abs_boundary(level_zip, country=country_obj, level=level,
                                      lang_suffix=lang_suffix)
                results.append({'level': level, 'status': 'ok',
                                'features': _count_loaded(iso2, iso3, level)})
            except Exception as e:
                logger.exception("Failed to load level %s", level)
                results.append({'level': level, 'status': 'error', 'message': str(e)})
            finally:
                shutil.rmtree(norm_dir, ignore_errors=True)

        return {
            'source_url': source_url,
            'resource': resource_name,
            'lang_suffix': lang_suffix,
            'levels': results,
        }
    finally:
        if zip_path and os.path.exists(zip_path):
            os.unlink(zip_path)
        shutil.rmtree(extract_dir, ignore_errors=True)


def clear_admin_boundaries():
    """
    Delete every ``AdminBoundary`` row for the configured country (all levels).
    Returns ``{deleted: int}``. Raises :class:`BoundaryImportError` if deps are
    missing or no country is configured.
    """
    _require_boundary_manager()
    iso2, iso3 = _country_codes()
    if not iso2 and not iso3:
        raise BoundaryImportError("Country is not configured.")

    from adminboundarymanager.models import AdminBoundary
    deleted, _ = AdminBoundary.objects.filter(_country_filter(iso2, iso3)).delete()
    return {'deleted': deleted}
