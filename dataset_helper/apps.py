from django.apps import AppConfig


class DatasetHelperConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dataset_helper'
    # The app label is deliberately kept as the old plugin name. Django derives
    # table names (dataset_helper_plugin_catalogentry, ...) and the `app` column
    # in django_migrations from the label, so pinning it here lets existing
    # installs upgrade in place with no data migration.
    label = 'dataset_helper_plugin'
    verbose_name = 'Dataset Helper'

