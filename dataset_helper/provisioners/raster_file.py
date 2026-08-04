"""Provisioner for layer_type=raster_file (download a remote GeoTIFF and ingest it)."""
import math
import os

from django.core.files import File
from django.utils import timezone

from geomanager.models.raster_file import LayerRasterFile, RasterFileLayer, RasterUpload
from geomanager.models.raster_style import RasterStyle
from geomanager.utils.raster_utils import create_layer_raster_file, read_raster_info

from ._shared import DEFAULT_RASTER_PALETTE, download_file, resolve_file_url


def provision(entry, dataset):
    """Download a remote GeoTIFF, ingest it, then create a RasterStyle from band stats."""
    url = resolve_file_url(entry.file_url)
    file_path = download_file(url, suffix='.tif', bearer=entry.file_bearer or None)
    try:
        layer = RasterFileLayer.objects.create(
            dataset=dataset,
            title=entry.layer_title or entry.title,
            default=True,
        )
        raster_file_row = _ingest(layer, dataset, file_path)
        layer.style = _create_default_style_from_metadata(
            name=entry.layer_title or entry.title,
            raster_metadata=raster_file_row.raster_metadata,
        )
        layer.save(update_fields=['style'])
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


def _ingest(layer, dataset, file_path):
    """Register an already-downloaded GeoTIFF as a LayerRasterFile; return the LayerRasterFile."""
    with open(file_path, 'rb') as f:
        upload = RasterUpload.objects.create(
            dataset=dataset,
            file=File(f, name=os.path.basename(file_path)),
        )

    raster_meta = read_raster_info(upload.file.path)
    upload.raster_metadata = raster_meta
    upload.save(update_fields=['raster_metadata'])

    time = timezone.now().replace(minute=0, second=0, microsecond=0)
    create_layer_raster_file(layer, upload, time)
    upload.delete()
    # create_layer_raster_file does not return the row — fetch by (layer, time).
    return LayerRasterFile.objects.get(layer=layer, time=time)


def _create_default_style_from_metadata(name, raster_metadata):
    """
    RasterStyle with a default diverging palette using band-1 min/max from
    LayerRasterFile.raster_metadata. Falls back to (0, 100) if stats are missing.
    Expected structure: ``{"bands": {"1": {"min": ..., "max": ...}}}``.
    """
    meta = raster_metadata or {}
    band_stats = meta.get('bands', {}).get('1', {})
    min_val = band_stats.get('min')
    max_val = band_stats.get('max')

    if min_val is None or max_val is None:
        min_val, max_val = 0, 100

    imin = int(math.floor(min_val))
    imax = int(math.ceil(max_val))
    if imax <= imin:
        imax = imin + 1

    return RasterStyle.objects.create(
        name=(name or 'raster')[:256],
        min=imin,
        max=imax,
        steps=9,
        palette=DEFAULT_RASTER_PALETTE,
        legend_type='choropleth_vertical',
        interpolate=False,
    )
