from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0007_is_pmtiles'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='popup_config_json',
            field=models.JSONField(
                blank=True,
                null=True,
                verbose_name='Popup config',
                help_text='List of fields shown when a feature is clicked. '
                          'Each item: {data_key, label, data_type}.',
            ),
        ),
    ]
