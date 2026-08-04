from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0009_ecmwf_token_and_private'),
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
                ],
                default='wms',
                max_length=20,
                verbose_name='Layer type',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='cog_url_template',
            field=models.CharField(
                blank=True, default='', max_length=2048,
                verbose_name='COG URL template',
                help_text='URL template with a time placeholder, e.g. '
                          'https://example.org/data/file_{time:%Y}.tif',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='cog_time_start',
            field=models.DateTimeField(blank=True, null=True, verbose_name='COG time start'),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='cog_time_end',
            field=models.DateTimeField(blank=True, null=True, verbose_name='COG time end'),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='cog_time_step_value',
            field=models.PositiveIntegerField(default=1, verbose_name='COG time step value'),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='cog_time_step_unit',
            field=models.CharField(
                default='years', max_length=20,
                verbose_name='COG time step unit',
                help_text='One of: years, months, days, hours',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='cog_date_format',
            field=models.CharField(
                blank=True, default='', max_length=100,
                verbose_name='COG datetime display format',
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='raster_style_json',
            field=models.JSONField(
                blank=True, null=True,
                verbose_name='Raster style',
                help_text='Raster style definition: {min, max, steps, palette, '
                          'interpolate, legend_type, unit}',
            ),
        ),
    ]
