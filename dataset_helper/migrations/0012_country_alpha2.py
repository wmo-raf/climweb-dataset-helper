from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0011_country_bbox'),
    ]

    operations = [
        migrations.AddField(
            model_name='pluginsettings',
            name='country_alpha2',
            field=models.CharField(
                blank=True, default='', max_length=2,
                verbose_name='Country code (alpha-2)',
                help_text='ISO 3166-1 alpha-2 country code used for URL placeholder substitution (e.g. bf)',
            ),
        ),
    ]
