from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataset_helper_plugin', '0004_multi_layer_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='catalogentry',
            name='category_order',
            field=models.IntegerField(default=0, verbose_name='Category sort order'),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='subcategory_order',
            field=models.IntegerField(default=0, verbose_name='Subcategory sort order'),
        ),
        migrations.AddField(
            model_name='catalogentry',
            name='entry_order',
            field=models.IntegerField(default=0, verbose_name='Entry sort order'),
        ),
        migrations.AlterModelOptions(
            name='catalogentry',
            options={
                'ordering': ['category_order', 'subcategory_order', 'entry_order', 'title'],
                'verbose_name': 'Catalog Entry',
                'verbose_name_plural': 'Catalog Entries',
            },
        ),
    ]
