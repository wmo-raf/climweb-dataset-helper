# Same base image as ClimWeb: GDAL 3.7.0 and Python 3.10.6 preinstalled. GeoManager
# pulls in rasterio/rioxarray/netCDF4, which need GDAL headers at build time.
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.7.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=sandbox.settings.dev

EXPOSE 8000

RUN apt-get update --yes --quiet && apt-get install --yes --quiet --no-install-recommends \
    build-essential \
    python3-dev \
    python3-pip \
    libpq-dev \
    libgdal-dev \
    libjpeg-turbo8-dev \
    zlib1g-dev \
    libwebp-dev \
    libcairo2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The package lives one level up from the sandbox, so the build context is the repo
# root (see docker-compose.yml) and `-e ..` in requirements.txt resolves.
COPY setup.cfg pyproject.toml README.md LICENSE MANIFEST.in /app/
COPY dataset_helper /app/dataset_helper
COPY sandbox/requirements.txt /app/sandbox/requirements.txt

RUN python3 -m pip install --no-cache-dir --upgrade pip \
 && python3 -m pip install --no-cache-dir -r /app/sandbox/requirements.txt

COPY sandbox /app/sandbox

WORKDIR /app/sandbox

CMD ["bash", "./entrypoint.sh"]
