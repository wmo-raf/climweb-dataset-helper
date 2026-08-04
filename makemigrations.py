#!/usr/bin/env python

from django.core.management import call_command

from boot_django import boot_django

boot_django()
# Note: the app label is "dataset_helper_plugin", not the module name.
call_command("makemigrations", "dataset_helper_plugin")
