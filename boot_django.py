import os

import django
from django.conf import settings

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "dataset_helper"))
SANDBOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "sandbox"))

SECRET_KEY = "django-insecure-dataset-helper-local-only-do-not-use-in-production"

INSTALLED_APPS = [
    "dataset_helper",

    "wagtail",
    "taggit",

    "django.contrib.auth",
    "django.contrib.contenttypes",
]

# The app ships raw PostgreSQL in migrations 0006 and 0023, and geomanager needs
# PostGIS, so migrate.py talks to a real database. Override with env vars.
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("DB_NAME", "dataset_helper"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}


def boot_django():
    settings.configure(
        BASE_DIR=BASE_DIR,
        DEBUG=True,
        INSTALLED_APPS=INSTALLED_APPS,
        TIME_ZONE="UTC",
        USE_TZ=True,
        SECRET_KEY=SECRET_KEY,
        DATABASES=DATABASES,
    )
    django.setup()
