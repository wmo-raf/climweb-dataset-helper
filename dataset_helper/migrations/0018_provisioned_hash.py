from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0017_source_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='provisioned_hash',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Provisioned content hash'),
        ),
    ]
