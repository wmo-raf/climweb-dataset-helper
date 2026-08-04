from django.db import migrations


class Migration(migrations.Migration):
    """
    Add DB-level DEFAULT false to ``popup`` and ``legend_from_capabilities``.

    The model fields already carry a Python-level default, but Django drops
    the DB default after backfilling existing rows. Restoring it makes
    INSERTs resilient to partial deploys where the migration is applied
    before the code that knows about the new fields lands — the column
    silently defaults to false instead of raising NOT NULL.
    """

    dependencies = [
        ('dataset_helper_plugin', '0022_legend_from_capabilities'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE dataset_helper_plugin_catalogentry "
                "ALTER COLUMN popup SET DEFAULT false;",
                "ALTER TABLE dataset_helper_plugin_catalogentry "
                "ALTER COLUMN legend_from_capabilities SET DEFAULT false;",
            ],
            reverse_sql=[
                "ALTER TABLE dataset_helper_plugin_catalogentry "
                "ALTER COLUMN popup DROP DEFAULT;",
                "ALTER TABLE dataset_helper_plugin_catalogentry "
                "ALTER COLUMN legend_from_capabilities DROP DEFAULT;",
            ],
        ),
    ]
