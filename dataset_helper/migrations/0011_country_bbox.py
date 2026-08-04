from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0010_raster_cog'),
    ]

    operations = [
        migrations.AddField(
            model_name='pluginsettings',
            name='country_bbox',
            field=models.JSONField(
                blank=True, null=True,
                verbose_name='Country bounding box',
                help_text='Nominatim country bounding box as [south, north, west, east] of decimal degrees',
            ),
        ),
    ]
