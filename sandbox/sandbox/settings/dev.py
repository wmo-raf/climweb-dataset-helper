from .base import *  # noqa: F401,F403

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# SECURITY WARNING: this key is public. The sandbox is a local test harness only.
SECRET_KEY = "django-insecure-dataset-helper-sandbox-do-not-use-in-production"

ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

GDAL_LIBRARY_PATH = os.getenv("GDAL_LIBRARY_PATH", None)  # noqa: F405
GEOS_LIBRARY_PATH = os.getenv("GEOS_LIBRARY_PATH", None)  # noqa: F405

try:
    from .local import *  # noqa: F401,F403
except ImportError:
    pass
