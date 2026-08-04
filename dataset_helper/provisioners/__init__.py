"""Per-layer-type provisioning logic.

Each module here exports a ``provision(entry, dataset)`` function that
materialises the geomanager Layer object(s) for a given CatalogEntry.
The ``PROVISIONERS`` dict below is the single source of truth that
``services.sync_catalog_to_climweb`` dispatches against.
"""
from . import raster_file, vector_file

PROVISIONERS = {
    'raster_file': raster_file.provision,
    'vector_file': vector_file.provision,
}
