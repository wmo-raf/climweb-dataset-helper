from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0019_provisioned_source_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='initial_visible',
            field=models.BooleanField(default=False, help_text='If set, the dataset is enabled on the map by default.', verbose_name='Initially visible on map'),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='auto_update_interval',
            field=models.IntegerField(blank=True, help_text='Auto-refresh interval for multi-temporal layers, in minutes. Leave empty to disable auto-updating.', null=True, verbose_name='Auto update interval (minutes)'),
        ),
    ]
