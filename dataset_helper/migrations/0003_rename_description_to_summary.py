from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0002_pluginsettings'),
    ]

    operations = [
        migrations.RenameField(
            model_name='catalogentry',
            old_name='description',
            new_name='summary',
        ),
    ]
