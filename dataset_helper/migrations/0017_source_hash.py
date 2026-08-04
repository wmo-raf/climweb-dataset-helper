from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0016_catalogstate'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='source_hash',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Catalog content hash'),
        ),
    ]
