from geomanager.models.core import Dataset, Category, SubCategory, Metadata
from geomanager.models.raster_style import RasterStyle
from geomanager.models.wms import WmsLayer, WmsRequestLayer
from django.shortcuts import render
from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import F
import json
import logging

logger = logging.getLogger(__name__)

from .models import CatalogEntry, CatalogState, PluginSettings
from . import services
from . import boundaries

# Valid layer types from Dataset.DATASET_TYPE_CHOICES
VALID_LAYER_TYPES = ('raster_file', 'vector_file', 'wms', 'raster_tile', 'vector_tile')


def index(request):
    template_name = "dataset_helper/index.html"
    s = PluginSettings.load()
    # Country is the only mandatory setting. While it is unset the UI lands on
    # the Settings tab and locks the others until it is saved.
    settings_valid = bool(s.country_alpha3 and len(s.country_alpha3) == 3)
    return render(request, template_name, {
        'plugin_settings': s,
        'settings_valid': settings_valid,
    })


# ── Catalog API ──────────────────────────────────────────────────────────────


def catalog_tree(request):
    """Return the full catalog as a JSON tree for the UI."""
    try:
        tree = services.get_catalog_tree()
        total = CatalogEntry.objects.count()
        enabled = CatalogEntry.objects.filter(enabled=True).count()
        synced = CatalogEntry.objects.exclude(dataset_id=None).filter(enabled=True).count()

        # Live drift between the catalog selection and what is actually
        # provisioned in Climweb. Surfaced so the admin sees immediately
        # whether a "Synchronize with Climweb" is pending.
        pending_add = CatalogEntry.objects.filter(
            enabled=True, dataset_id__isnull=True,
        ).count()
        pending_remove = CatalogEntry.objects.filter(
            enabled=False, dataset_id__isnull=False,
        ).count()
        # Synced entries whose catalog content moved since the last sync:
        # Climweb still holds the stale version until re-synced.
        pending_update = (
            CatalogEntry.objects
            .filter(enabled=True, dataset_id__isnull=False)
            .exclude(provisioned_source_hash='')
            .exclude(source_hash=F('provisioned_source_hash'))
            .count()
        )
        out_of_sync = pending_add + pending_remove + pending_update

        embedded_version, embedded_schema = services.get_embedded_catalog_version()
        state = CatalogState.load()
        update_available = bool(
            embedded_version and embedded_version != state.loaded_version
        )

        return JsonResponse({
            'status': 'success',
            'total': total,
            'enabled': enabled,
            'synced': synced,
            'pending_add': pending_add,
            'pending_remove': pending_remove,
            'pending_update': pending_update,
            'out_of_sync': out_of_sync,
            'categories': tree,
            'embedded_version': embedded_version,
            'embedded_schema_version': embedded_schema,
            'loaded_version': state.loaded_version,
            'loaded_schema_version': state.loaded_schema_version,
            'loaded_at': state.loaded_at.isoformat() if state.loaded_at else None,
            'update_available': update_available,
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': _('Server error: %(error)s') % {'error': e}}, status=500)


def catalog_preview_embedded(request):
    """
    Dry-run: return the changeset that would result from loading the
    embedded catalog into the database, without writing anything.
    """
    try:
        changeset = services.preview_embedded_catalog()
    except FileNotFoundError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    except ValueError as e:
        return JsonResponse(
            {'status': 'error', 'message': _('Invalid embedded catalog JSON: %(error)s') % {'error': e}},
            status=500,
        )
    except Exception as e:
        logger.exception("catalog_preview_embedded failed")
        return JsonResponse({'status': 'error', 'message': _('Server error: %(error)s') % {'error': e}}, status=500)

    return JsonResponse({'status': 'success', **changeset})


@csrf_exempt
@require_POST
def catalog_load_embedded(request):
    """
    Load the bundled catalog.json directly from disk. The browser does not
    need to (and must not) fetch the static file itself, because a stale
    cached or collectstatic'd copy would silently replace the live data
    with old content.

    Optional JSON body: {"conflict_policy": "skip"|"overwrite"}. Defaults to
    "overwrite" for backward compatibility; the preview-driven UI sends
    "skip" explicitly when the admin chose to preserve local Wagtail edits.
    """
    conflict_policy = 'overwrite'
    if request.body:
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError as e:
            return JsonResponse({'status': 'error', 'message': _('Invalid JSON: %(error)s') % {'error': e}}, status=400)
        policy = body.get('conflict_policy')
        if policy not in (None, 'skip', 'overwrite'):
            return JsonResponse(
                {'status': 'error',
                 'message': _("conflict_policy must be 'skip' or 'overwrite', got %(policy)r") % {'policy': policy}},
                status=400,
            )
        if policy is not None:
            conflict_policy = policy

    try:
        stats = services.load_embedded_catalog(conflict_policy=conflict_policy)
    except FileNotFoundError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    except ValueError as e:
        return JsonResponse(
            {'status': 'error', 'message': _('Invalid embedded catalog JSON: %(error)s') % {'error': e}},
            status=500,
        )
    except Exception as e:
        logger.exception("catalog_load_embedded failed")
        return JsonResponse({'status': 'error', 'message': _('Server error: %(error)s') % {'error': e}}, status=500)

    if stats['created'] == 0 and stats['updated'] == 0 and stats['errors']:
        return JsonResponse({
            'status': 'error',
            'message': stats['errors'][0],
            **stats,
        }, status=400)

    msg = _('Catalog loaded: %(created)d created, %(updated)d updated, %(unchanged)d unchanged') % {
        'created': stats['created'],
        'updated': stats['updated'],
        'unchanged': stats['unchanged'],
    }
    if stats.get('conflict_skipped'):
        msg += _(', %(count)d conflicts kept local') % {'count': stats['conflict_skipped']}
    if stats.get('removed'):
        msg += _(', %(count)d disabled (gone from JSON)') % {'count': stats['removed']}
    if stats.get('skipped_estation'):
        msg += _(', %(count)d skipped (not on local eStation)') % {'count': stats['skipped_estation']}
    if stats.get('skipped_out_of_coverage'):
        msg += _(', %(count)d skipped (no data over the country)') % {'count': stats['skipped_out_of_coverage']}

    return JsonResponse({
        'status': 'success',
        'message': msg,
        **stats,
    })


@csrf_exempt
@require_POST
def catalog_sync(request):
    """Provision enabled entries to Climweb and deprovision disabled ones."""
    try:
        stats = services.sync_catalog_to_climweb()
        parts = [
            _('%(count)d added') % {'count': stats['added']},
            _('%(count)d removed') % {'count': stats['removed']},
            _('%(count)d updated') % {'count': stats['reprovisioned']},
            _('%(count)d orphans cleared') % {'count': stats['orphans_cleared']},
        ]
        if stats.get('raster_file_drift'):
            parts.append(_('%(count)d raster_file drift (skipped)') % {'count': stats['raster_file_drift']})
        return JsonResponse({
            'status': 'success',
            'message': _('Sync complete: %(parts)s') % {'parts': ", ".join(parts)},
            **stats,
        })
    except Exception as e:
        logger.exception("catalog_sync failed")
        return JsonResponse({'status': 'error', 'message': _('Sync failed: %(error)s') % {'error': e}}, status=500)


@csrf_exempt
@require_POST
def catalog_toggle(request, entry_id):
    """Toggle the enabled flag on a single catalog entry."""
    try:
        entry = CatalogEntry.objects.get(id=entry_id)
    except CatalogEntry.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': _('Entry not found')}, status=404)

    entry.enabled = not entry.enabled
    entry.save(update_fields=['enabled', 'updated_at'])
    return JsonResponse({
        'status': 'success',
        'id': str(entry.id),
        'enabled': entry.enabled,
        'new_status': entry.status,
    })


@csrf_exempt
@require_POST
def catalog_bulk_toggle(request):
    """Set enabled flag for multiple catalog entries at once."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError as e:
        return JsonResponse({'status': 'error', 'message': _('Invalid JSON: %(error)s') % {'error': e}}, status=400)

    entry_ids = data.get('entry_ids', [])
    enabled = data.get('enabled', True)

    if not entry_ids:
        return JsonResponse({'status': 'error', 'message': _('No entry_ids provided')}, status=400)

    updated = CatalogEntry.objects.filter(id__in=entry_ids).update(enabled=enabled)
    return JsonResponse({
        'status': 'success',
        'updated': updated,
        'enabled': enabled,
    })


@csrf_exempt
@require_POST
def catalog_reset(request):
    """
    Wipe everything this plugin tracks: delete the Climweb Datasets it
    provisioned (selective — non-plugin Datasets, Categories and
    SubCategories are kept), then delete all CatalogEntry rows (config,
    manual, wms_import) and clear CatalogState.

    Order matters: clear_provisioned_datasets reads dataset_id from
    CatalogEntry, so it must run before the entries are deleted.
    """
    try:
        clear_stats = services.clear_provisioned_datasets()

        entries_deleted = CatalogEntry.objects.count()
        CatalogEntry.objects.all().delete()

        state = CatalogState.load()
        state.loaded_version = ''
        state.loaded_schema_version = 0
        state.loaded_at = None
        state.save()

        return JsonResponse({
            'status': 'success',
            'message': _(
                'Catalog reset: %(entries)d catalog entries deleted, '
                '%(datasets)d Climweb Dataset(s) removed, '
                '%(metadata)d Metadata removed, '
                '%(subcats)d empty SubCategor(ies) swept, '
                '%(cats)d empty Categor(ies) swept'
            ) % {
                'entries': entries_deleted,
                'datasets': clear_stats['datasets_deleted'],
                'metadata': clear_stats['metadata_deleted'],
                'subcats': clear_stats['subcategories_deleted'],
                'cats': clear_stats['categories_deleted'],
            },
            'deleted': entries_deleted,
            **clear_stats,
        })
    except Exception as e:
        logger.exception("catalog_reset failed")
        return JsonResponse({'status': 'error', 'message': _('Reset failed: %(error)s') % {'error': e}}, status=500)


# ── Settings API ────────────────────────────────────────────────────────────


def settings_get(request):
    """Return current plugin settings."""
    s = PluginSettings.load()
    return JsonResponse({
        'status': 'success',
        'language': s.language,
        'ecmwf_token': s.ecmwf_token,
        'estation_url': s.estation_url,
        'country_alpha3': s.country_alpha3,
        'country_alpha2': s.country_alpha2,
        'country_name': s.country_name,
        'country_bbox': s.country_bbox,
    })


@csrf_exempt
@require_POST
def settings_save(request):
    """Update plugin settings."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError as e:
        return JsonResponse({'status': 'error', 'message': _('Invalid JSON: %(error)s') % {'error': e}}, status=400)

    s = PluginSettings.load()

    if 'language' in data:
        lang = data['language']
        if lang not in dict(PluginSettings.LANGUAGE_CHOICES):
            return JsonResponse({'status': 'error', 'message': _('Invalid language: %(lang)s') % {'lang': lang}}, status=400)
        s.language = lang

    if 'ecmwf_token' in data:
        s.ecmwf_token = (data['ecmwf_token'] or '').strip()

    if 'estation_url' in data:
        s.estation_url = data['estation_url'] or ''

    # Country is mandatory: alpha3 + alpha2 + name + bbox are saved together.
    if any(k in data for k in ('country_alpha3', 'country_alpha2', 'country_name', 'country_bbox')):
        alpha3 = (data.get('country_alpha3') or '').strip().lower()[:3]
        if not alpha3 or len(alpha3) != 3 or not alpha3.isalpha():
            return JsonResponse(
                {'status': 'error', 'message': _('country_alpha3 is required (ISO 3166-1 alpha-3)')},
                status=400,
            )
        alpha2 = (data.get('country_alpha2') or '').strip().lower()[:2]
        if not alpha2 or len(alpha2) != 2 or not alpha2.isalpha():
            return JsonResponse(
                {'status': 'error', 'message': _('country_alpha2 is required (ISO 3166-1 alpha-2)')},
                status=400,
            )
        name = (data.get('country_name') or '').strip()[:255]
        if not name:
            return JsonResponse(
                {'status': 'error', 'message': _('country_name is required')},
                status=400,
            )
        bbox = data.get('country_bbox')
        if not (isinstance(bbox, list) and len(bbox) == 4
                and all(isinstance(v, (int, float)) for v in bbox)):
            return JsonResponse(
                {'status': 'error',
                 'message': _('country_bbox must be a list of 4 numbers [south, north, west, east]')},
                status=400,
            )
        s.country_alpha3 = alpha3
        s.country_alpha2 = alpha2
        s.country_name = name
        s.country_bbox = [float(v) for v in bbox]

    s.save()
    return JsonResponse({
        'status': 'success',
        'message': _('Settings saved'),
        'language': s.language,
        'ecmwf_token': s.ecmwf_token,
        'estation_url': s.estation_url,
        'country_alpha3': s.country_alpha3,
        'country_bbox': s.country_bbox,
    })


@csrf_exempt
@require_POST
def catalog_clear_provisioned(request):
    """
    Delete only the Climweb Datasets that this plugin provisioned.
    Categories, SubCategories, and external (non-plugin) Datasets are
    left alone. CatalogEntry rows remain — their dataset_id and hashes
    are cleared, so they go back to pending_add for a future sync.
    """
    try:
        stats = services.clear_provisioned_datasets()
    except Exception as e:
        logger.exception("catalog_clear_provisioned failed")
        return JsonResponse({'status': 'error', 'message': _('Clear failed: %(error)s') % {'error': e}}, status=500)

    return JsonResponse({
        'status': 'success',
        'message': _(
            'Cleared catalog-managed data: '
            '%(datasets)d Dataset(s), '
            '%(metadata)d Metadata, '
            '%(subcats)d empty SubCategor(ies), '
            '%(cats)d empty Categor(ies). '
            '%(entries)d catalog entries reset to pending_add.'
        ) % {
            'datasets': stats['datasets_deleted'],
            'metadata': stats['metadata_deleted'],
            'subcats': stats['subcategories_deleted'],
            'cats': stats['categories_deleted'],
            'entries': stats['entries_reset'],
        },
        **stats,
    })


# ── Admin Boundaries API (OCHA / HDX COD-AB) ─────────────────────────────────


def boundaries_status(request):
    """Return the current state of the admin-boundaries feature."""
    try:
        return JsonResponse({'status': 'success', **boundaries.get_boundaries_status()})
    except Exception as e:
        logger.exception("boundaries_status failed")
        return JsonResponse({'status': 'error', 'message': _('Server error: %(error)s') % {'error': e}}, status=500)


@csrf_exempt
@require_POST
def boundaries_import(request):
    """
    Download the OCHA COD-AB boundaries for the configured country and load
    every admin level into the boundary manager.
    """
    try:
        result = boundaries.import_admin_boundaries()
    except boundaries.BoundaryImportError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        logger.exception("boundaries_import failed")
        return JsonResponse({'status': 'error', 'message': _('Import failed: %(error)s') % {'error': e}}, status=500)

    ok = sum(1 for lvl in result['levels'] if lvl['status'] == 'ok')
    failed = sum(1 for lvl in result['levels'] if lvl['status'] == 'error')
    features = sum(lvl.get('features', 0) for lvl in result['levels'])
    msg = _('Boundaries imported: %(ok)d level(s), %(features)d features') % {'ok': ok, 'features': features}
    if failed:
        msg += _(', %(failed)d level(s) failed') % {'failed': failed}

    return JsonResponse({'status': 'success', 'message': msg, **result})


@csrf_exempt
@require_POST
def boundaries_clear(request):
    """Delete every AdminBoundary row for the configured country."""
    try:
        stats = boundaries.clear_admin_boundaries()
    except boundaries.BoundaryImportError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        logger.exception("boundaries_clear failed")
        return JsonResponse({'status': 'error', 'message': _('Clear failed: %(error)s') % {'error': e}}, status=500)

    return JsonResponse({
        'status': 'success',
        'message': _('%(count)d boundary feature(s) deleted') % {'count': stats['deleted']},
        **stats,
    })


@csrf_exempt
@require_POST
def clear_all(request):
    """
    Clear all datasets and categories.
    This will delete all WmsRequestLayer, WmsLayer, Metadata, Dataset, SubCategory, and Category objects.
    """
    deleted = {
        'wms_request_layers': 0,
        'wms_layers': 0,
        'raster_styles': 0,
        'datasets': 0,
        'metadata': 0,
        'subcategories': 0,
        'categories': 0,
    }
    errors = []

    # Delete in order (respecting foreign key constraints)
    # Bulk deletes for child models that are unlikely to have external references
    for model, key in [
        (WmsRequestLayer, 'wms_request_layers'),
        (WmsLayer, 'wms_layers'),
    ]:
        try:
            count, _ = model.objects.all().delete()
            deleted[key] = count
        except Exception as e:
            errors.append(f"Failed to bulk delete {key}: {e}")

    # Delete datasets, metadata, subcategories, categories one by one to skip protected ones
    # (raster styles are deleted after datasets because RasterFileLayer.style uses SET_NULL,
    # so they aren't removed by the dataset cascade)
    for model, key in [
        (Metadata, 'metadata'),
        (Dataset, 'datasets'),
        (RasterStyle, 'raster_styles'),
        (SubCategory, 'subcategories'),
        (Category, 'categories'),
    ]:
        for obj in model.objects.all():
            try:
                obj.delete()
                deleted[key] += 1
            except Exception as e:
                errors.append(f"Could not delete {key[:-1]} '{obj}': {e}")

    # Clear dataset_id references in catalog entries
    CatalogEntry.objects.exclude(dataset_id=None).update(dataset_id=None)

    if errors:
        return JsonResponse({
            'status': 'partial',
            'message': _('Completed with %(count)d error(s)') % {'count': len(errors)},
            'deleted': deleted,
            'errors': errors,
        })

    return JsonResponse({
        'status': 'success',
        'message': _('All data cleared successfully'),
        'deleted': deleted,
    })
