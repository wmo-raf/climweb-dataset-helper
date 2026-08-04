from django.urls import path, reverse, include
from wagtail import hooks
from wagtail.admin.menu import MenuItem

from . import urls as plugin_urls


@hooks.register('register_admin_urls')
def register_dataset_helper_url():
    return [
        path('geomanager/dataset_helper/', include((plugin_urls, 'dataset_helper'))),
    ]


@hooks.register('register_geo_manager_menu_item')
def register_geo_manager_dataset_helper_item():
    url = reverse('dataset_helper:index')
    return MenuItem('Dataset helper', url, icon_name='pick', order=1.5)
