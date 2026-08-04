"""
Django settings for the Dataset Helper sandbox.

A minimal Wagtail project that runs GeoManager and Dataset Helper on their own, so the
app can be exercised without standing up a full ClimWeb instance.
"""

import os

import dj_database_url

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(PROJECT_DIR)

INSTALLED_APPS = [
    # The app under test. Its module is `dataset_helper`; the Django app label is
    # `dataset_helper_plugin` (kept from its life as a ClimWeb plugin), so management
    # commands take that label: `python manage.py migrate dataset_helper_plugin`.
    "dataset_helper",

    # GeoManager and everything it expects to find in INSTALLED_APPS.
    "geomanager",
    "adminboundarymanager",
    "django_large_image",
    "django_json_widget",
    "django_nextjs",
    "django_filters",
    "django_countries",
    "wagtail_color_panel",
    "wagtail_adminsortable",
    "wagtailhumanitarianicons",
    "wagtailiconchooser",
    "wagtailfontawesomesvg",
    "wagtail_modeladmin",
    "wagtailcache",
    "django_extensions",
    "allauth",
    "allauth.account",

    "wagtail.contrib.settings",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.routable_page",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",

    "modelcluster",
    "taggit",
    "rest_framework",
    "rest_framework.authtoken",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
]

ROOT_URLCONF = "sandbox.urls"
WSGI_APPLICATION = "sandbox.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            os.path.join(PROJECT_DIR, "templates"),
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "wagtail.contrib.settings.context_processors.settings",
            ],
        },
    },
]

# Dataset Helper needs PostGIS: GeoManager stores geometry, and migrations 0006 and
# 0023 contain raw PostgreSQL. See docker-compose.yml for a ready-made database.
DB_ENGINE = "sandbox.db_engine"

DATABASES = {
    "default": dj_database_url.config(
        default="postgis://postgres:postgres@localhost:5432/dataset_helper",
        engine=DB_ENGINE,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Dataset Helper ships translations for these, and the catalog carries titles in each.
LANGUAGES = WAGTAIL_CONTENT_LANGUAGES = [
    ("en", "English"),
    ("fr", "Français"),
    ("es", "Español"),
    ("pt", "Português"),
    ("ar", "العربية"),
]

LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "en")
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    # Serves dataset_helper/static/dataset_helper/catalog.json straight out of the
    # installed package - no STATICFILES_DIRS entry needed.
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

WAGTAIL_SITE_NAME = "Dataset Helper sandbox"
WAGTAILADMIN_BASE_URL = os.getenv("WAGTAILADMIN_BASE_URL", "http://localhost:8000")

WAGTAILSEARCH_BACKENDS = {
    "default": {
        "BACKEND": "wagtail.search.backends.database",
    }
}

# wagtail-cache, required by geomanager.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dataset-helper-sandbox",
    }
}
WAGTAIL_CACHE = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "formatters": {
        "verbose": {
            "format": "[%(asctime)s][%(process)d][%(levelname)s][%(name)s] %(message)s"
        },
    },
    "loggers": {
        "": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "wagtail": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "dataset_helper": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
