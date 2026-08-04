from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0012_country_alpha2'),
    ]

    operations = [
        migrations.AddField(
            model_name='pluginsettings',
            name='country_name',
            field=models.CharField(
                blank=True, default='', max_length=255,
                verbose_name='Country name',
                help_text='Official country name from OpenStreetMap Nominatim (display_name)',
            ),
        ),
    ]
