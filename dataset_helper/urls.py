from django.urls import path
from django.views.i18n import JavaScriptCatalog

from . import views

urlpatterns = [
    # JS translation catalog
    path('jsi18n/', JavaScriptCatalog.as_view(packages=['dataset_helper']), name='js_catalog'),


    # Catalog API
    path('catalog/', views.catalog_tree, name='catalog_tree'),
    path('catalog/load-embedded/', views.catalog_load_embedded, name='catalog_load_embedded'),
    path('catalog/preview-embedded/', views.catalog_preview_embedded, name='catalog_preview_embedded'),
    path('catalog/sync/', views.catalog_sync, name='catalog_sync'),
    path('catalog/<uuid:entry_id>/toggle/', views.catalog_toggle, name='catalog_toggle'),
    path('catalog/reset/', views.catalog_reset, name='catalog_reset'),
    path('catalog/clear-provisioned/', views.catalog_clear_provisioned, name='catalog_clear_provisioned'),
    path('catalog/bulk-toggle/', views.catalog_bulk_toggle, name='catalog_bulk_toggle'),

    # Settings API
    path('settings/', views.settings_get, name='settings_get'),
    path('settings/save/', views.settings_save, name='settings_save'),

    # Admin Boundaries API (OCHA / HDX COD-AB)
    path('boundaries/status/', views.boundaries_status, name='boundaries_status'),
    path('boundaries/import/', views.boundaries_import, name='boundaries_import'),
    path('boundaries/clear/', views.boundaries_clear, name='boundaries_clear'),

    # Legacy endpoints
    path('clear-all/', views.clear_all, name='clear_all'),
    path('', views.index, name='index'),
]

