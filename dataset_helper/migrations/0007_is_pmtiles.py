from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0006_legend_json'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='is_pmtiles',
            field=models.BooleanField(
                default=False,
                verbose_name='PMTiles format',
                help_text='For vector_tile layers: treat tile_url as a PMTiles archive URL instead of an XYZ template',
            ),
        ),
    ]
