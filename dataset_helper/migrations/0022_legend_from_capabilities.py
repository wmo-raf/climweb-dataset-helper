from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0021_popup'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='legend_from_capabilities',
            field=models.BooleanField(default=False, help_text='If checked, the legend will be loaded from the WMS GetCapabilities response (LegendURL).', verbose_name='Load legend from WMS capabilities'),
        ),
    ]
