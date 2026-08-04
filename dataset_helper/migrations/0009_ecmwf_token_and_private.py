from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0008_popup_config_json'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pluginsettings',
            name='ecmwf_token',
            field=models.CharField(
                blank=True,
                default='',
                max_length=255,
                verbose_name='ECMWF API Token',
                help_text=(
                    'Token for ECMWF eccharts WMS service. Leave empty to keep public layers '
                    'using token=public and skip private layers (token={ECMWF_TOKEN}).'
                ),
            ),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='public',
            field=models.BooleanField(
                default=True,
                verbose_name='Public',
                help_text='Propagated to Dataset.public. False for ECMWF private layers (token={ECMWF_TOKEN} in config).',
            ),
        ),
    ]
