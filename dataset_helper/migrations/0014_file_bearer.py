from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0013_country_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='file_bearer',
            field=models.CharField(
                blank=True, default='', max_length=2048,
                verbose_name='File bearer token',
                help_text=(
                    "Optional bearer token sent as 'Authorization: Bearer …' "
                    "when downloading file_url (e.g. APIs that require auth)."
                ),
            ),
        ),
    ]
