from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0015_near_realtime'),
    ]

    operations = [
        migrations.CreateModel(
            name='CatalogState',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('loaded_version', models.CharField(blank=True, default='', max_length=64, verbose_name='Loaded catalog version')),
                ('loaded_schema_version', models.PositiveIntegerField(default=0, verbose_name='Loaded catalog schema version')),
                ('loaded_at', models.DateTimeField(blank=True, null=True, verbose_name='Last load timestamp')),
            ],
            options={
                'verbose_name': 'Catalog State',
                'verbose_name_plural': 'Catalog State',
            },
        ),
    ]
