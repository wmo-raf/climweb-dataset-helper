from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0014_file_bearer'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='near_realtime',
            field=models.BooleanField(default=False),
        ),
    ]
