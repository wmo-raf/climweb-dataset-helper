from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0020_initial_visible_auto_update_interval'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='popup',
            field=models.BooleanField(default=False, help_text='If checked, a popup will be displayed when clicking on the layer.', verbose_name='Enable popup'),
        ),
    ]
