from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0024_reconcile_model_state'),
    ]

    operations = [
        migrations.AlterField(
            model_name='catalogentry',
            name='layer_type',
            field=models.CharField(
                choices=[
                    ('wms', 'WMS'),
                    ('raster_tile', 'Raster Tile'),
                    ('vector_tile', 'Vector Tile'),
                    ('raster_file', 'Raster File'),
                    ('vector_file', 'Vector File'),
                    ('raster_cog', 'Raster COG'),
                    ('openmeteo', 'Open-Meteo'),
                ],
                default='wms',
                max_length=20,
                verbose_name='Layer type',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='openmeteo_base_url',
            field=models.CharField(
                blank=True, default='', max_length=2048,
                verbose_name='Open-Meteo data base URL',
                help_text='Root URL of the Open-Meteo spatial data. Leave empty to use the GeoManager default.',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='openmeteo_domain',
            field=models.CharField(
                blank=True, default='', max_length=100,
                verbose_name='Open-Meteo weather model',
                help_text='Open-Meteo domain of the weather model, e.g. ecmwf_ifs025',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='openmeteo_variable',
            field=models.CharField(
                blank=True, default='', max_length=100,
                verbose_name='Open-Meteo variable',
                help_text='Weather variable to display, e.g. temperature_2m',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='openmeteo_date_format',
            field=models.CharField(
                blank=True, default='', max_length=100,
                verbose_name='Open-Meteo datetime display format',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='current_time_method',
            field=models.CharField(
                blank=True, default='', max_length=100,
                verbose_name='Current time method',
                help_text='How the map viewer picks the default time of a multi-temporal dataset. '
                          'Leave empty to use the GeoManager default.',
            ),
        ),
    ]
