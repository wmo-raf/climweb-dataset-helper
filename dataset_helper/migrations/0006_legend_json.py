from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0005_sort_order'),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE dataset_helper_plugin_catalogentry DROP COLUMN IF EXISTS dataset_group;',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='legend_json',
            field=models.JSONField(
                blank=True,
                null=True,
                verbose_name='Legend',
                help_text='Custom legend definition: {type, items: [{name, color}]}',
            ),
        ),
    ]
