from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PluginSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language', models.CharField(choices=[('en', 'English'), ('fr', 'Français'), ('es', 'Español'), ('pt', 'Português'), ('ar', 'العربية')], default='en', help_text='Language for imported catalog labels', max_length=2, verbose_name='Language')),
                ('ecmwf_token', models.CharField(default='public', help_text='Token for ECMWF eccharts WMS service', max_length=255, verbose_name='ECMWF API Token')),
                ('estation_url', models.URLField(blank=True, default='', help_text='If set, only eStation products available on this local instance will be imported', max_length=500, verbose_name='Local eStation URL')),
            ],
            options={
                'verbose_name': 'Plugin Settings',
                'verbose_name_plural': 'Plugin Settings',
            },
        ),
    ]
