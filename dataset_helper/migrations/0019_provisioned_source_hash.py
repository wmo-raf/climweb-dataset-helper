from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0018_provisioned_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='provisioned_source_hash',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Source hash at last sync'),
        ),
    ]
