from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0003_rename_description_to_summary'),
    ]

    operations = [
        # PluginSettings: add country_alpha3
        migrations.AddField(
            model_name='pluginsettings',
            name='country_alpha3',
            field=models.CharField(
                blank=True, default='', max_length=3,
                help_text='ISO 3166-1 alpha-3 country code used for URL placeholder substitution (e.g. bfa)',
                verbose_name='Country code (alpha-3)',
            ),
        ),
        # CatalogEntry: add layer_type
        migrations.AddField(
            model_name='catalogentry',
            name='layer_type',
            field=models.CharField(
                choices=[
                    ('wms', 'WMS'), ('raster_tile', 'Raster Tile'),
                    ('vector_tile', 'Vector Tile'), ('raster_file', 'Raster File'),
                    ('vector_file', 'Vector File'),
                ],
                default='wms', max_length=20, verbose_name='Layer type',
            ),
        ),
        # CatalogEntry: add tile_url
        migrations.AddField(
            model_name='catalogentry',
            name='tile_url',
            field=models.CharField(
                blank=True, default='', max_length=500,
                help_text='URL template with {z}/{x}/{y} placeholders',
                verbose_name='Tile URL',
            ),
        ),
        # CatalogEntry: add file_url
        migrations.AddField(
            model_name='catalogentry',
            name='file_url',
            field=models.CharField(
                blank=True, default='', max_length=500,
                help_text='URL to a remote file. May contain {country_alpha3} placeholder.',
                verbose_name='File URL',
            ),
        ),
        # CatalogEntry: add render_layers_json
        migrations.AddField(
            model_name='catalogentry',
            name='render_layers_json',
            field=models.JSONField(
                blank=True, null=True,
                help_text='MapLibre GL style layer definitions (JSON array)',
                verbose_name='Render layers',
            ),
        ),
        # CatalogEntry: add extra_params_json
        migrations.AddField(
            model_name='catalogentry',
            name='extra_params_json',
            field=models.JSONField(
                blank=True, null=True,
                help_text='Additional query parameters for WMS requests (JSON object)',
                verbose_name='Extra WMS params',
            ),
        ),
        # CatalogEntry: make layer_name optional
        migrations.AlterField(
            model_name='catalogentry',
            name='layer_name',
            field=models.CharField(
                blank=True, default='', max_length=255,
                help_text='Layer identifier as returned by WMS GetCapabilities',
                verbose_name='WMS layer name',
            ),
        ),
        # CatalogEntry: make wms_url optional (change to CharField)
        migrations.AlterField(
            model_name='catalogentry',
            name='wms_url',
            field=models.CharField(
                blank=True, default='', max_length=500,
                verbose_name='WMS base URL',
            ),
        ),
    ]
