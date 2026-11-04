# ClimWeb Dataset Helper

Wizards for ingesting reference datasets — WMS, raster (COG/tile), vector (tile/PMTiles),
Open-Meteo weather model forecasts and OCHA/HDX admin boundaries — into
[ClimWeb](https://github.com/wmo-raf/nmhs-cms) via GeoManager.

Previously distributed as a ClimWeb *plugin* (installed with `install_plugin.sh` into
`CLIMWEB_PLUGIN_DIR`). It is now an ordinary pip-installable Django/Wagtail app, packaged
the same way as [forecastmanager](https://github.com/wmo-raf/forecastmanager).

## Installation

ClimWeb ships `dataset_helper` in `INSTALLED_APPS` (next to `geomanager`), so on a
ClimWeb instance you only need the package present in the same Python environment:

```shell
pip install climweb-dataset-helper
```

Do **not** also set `CLIMWEB_ADDITIONAL_APPS=dataset_helper` — that would register the
app twice.

For any other Wagtail project, add it yourself:

```python
INSTALLED_APPS = [
    ...
    "geomanager",
    "dataset_helper",
    ...
]
```

Then run migrations. **Note the app label is `dataset_helper_plugin`, not the module
name** — see [App label](#app-label) below:

```shell
python manage.py migrate dataset_helper_plugin
```

The tool appears in the Wagtail admin under **GeoManager → Dataset helper**
(`/admin/geomanager/dataset_helper/`).

### Requirements

- Python >= 3.8 (ClimWeb runs 3.11)
- PostgreSQL/PostGIS — migrations `0006` and `0023` contain raw PostgreSQL
- `geomanager` >= 0.6, `wagtail` >= 6.0, `django` >= 4.2
- Optional, for the Admin Boundaries tab: `pip install "climweb-dataset-helper[boundaries]"`
  (`geopandas` + `adm-boundary-manager`). Both are imported lazily; without them the app
  still loads and the boundary endpoints return a clear error. ClimWeb already ships both.

## App label

The Python module is `dataset_helper`, but the Django **app label is pinned to
`dataset_helper_plugin`** in `apps.py`:

```python
class DatasetHelperConfig(AppConfig):
    name = 'dataset_helper'
    label = 'dataset_helper_plugin'
```

Django derives table names and the `app` column of `django_migrations` from the label,
so pinning it keeps the existing `dataset_helper_plugin_*` tables and migration history
intact. Sites upgrading from the plugin need **no data migration** — uninstall the
plugin, `pip install` this package, and carry on.

The practical consequence: management commands take the *label*.

```shell
python manage.py migrate dataset_helper_plugin
python manage.py sqlmigrate dataset_helper_plugin 0024
```

## Upgrading from the plugin

1. Back up the database (recommended, though no schema rewrite is involved).
2. Remove the old plugin: delete it from `CLIMWEB_PLUGIN_DIR` (or run its
   `uninstall.sh`), and drop `dataset_helper_plugin` from any plugin config.
3. `pip install climweb-dataset-helper`. On ClimWeb that is all — the app is already in
   `INSTALLED_APPS`. Remove `dataset_helper` from `CLIMWEB_ADDITIONAL_APPS` if it is set
   there.
4. `python manage.py migrate dataset_helper_plugin` — this applies only
   `0024_reconcile_model_state`, which closes pre-existing drift between `models.py` and
   the recorded migration state (four `CharField` definitions, plus the implicit `id`
   fields on `catalogstate`/`pluginsettings` which were still `AutoField`).

Two client-side names changed:

- Admin URL: `/admin/geomanager/dataset_helper_plugin/` → `/admin/geomanager/dataset_helper/`
- URL namespace / template directory: `dataset_helper_plugin` → `dataset_helper`

## What changed from the plugin

| Plugin | Package |
| --- | --- |
| `install_plugin.sh` into `CLIMWEB_PLUGIN_DIR` | `pip install climweb-dataset-helper` |
| Discovered via `climweb_plugin_info.json` | Listed in `INSTALLED_APPS` / `CLIMWEB_ADDITIONAL_APPS` |
| `apps.py` registered with `climweb.base.registries.plugin_registry` | Plain `AppConfig` — the registration was a no-op |
| `plugins.py` (`Plugin` subclass, returned no urls) | Removed; admin URLs come from `wagtail_hooks.py`, as before |
| `config/settings/plugin_settings.py` appended to `STATICFILES_DIRS` | Removed; the UI is self-contained HTML + CDN MapLibre, there are no bundled static files |
| Required a ClimWeb checkout on `sys.path` to import | Imports standalone; ClimWeb is reached only through `geomanager` |

`build.sh`, `uninstall.sh`, `Makefile` and `climweb_plugin_info.json` are gone — pip
handles all of it.

## Sandbox

`sandbox/` is a minimal Wagtail project running GeoManager and Dataset Helper on their
own, so you can exercise the app without standing up a full ClimWeb instance.

```shell
cd sandbox
docker compose up --build
```

Then open <http://localhost:8000/admin/geomanager/dataset_helper/> and log in with
`admin` / `admin` (created on first start; change it in `sandbox/.env`).

The compose file builds from the repo root and installs the package with `-e ..`, and
bind-mounts `dataset_helper/` into the container — edits to the app are picked up by the
dev server without a rebuild. Postgres is exposed on **5433** so it won't collide with a
local ClimWeb database.

Unlike forecastmanager's sandbox this one cannot use SQLite: GeoManager stores geometry,
and migrations `0006`/`0023` contain raw PostgreSQL. The compose file provides
`postgis/postgis:15-3.3`, and the image is built from the same GDAL base ClimWeb uses.

To run it without Docker, point `DATABASE_URL` at your own PostGIS database:

```shell
cd sandbox
pip install -r requirements.txt
export DATABASE_URL=postgis://postgres:postgres@localhost:5432/dataset_helper
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Open-Meteo datasets

The catalog lists the weather model forecasts published by
[Open-Meteo](https://open-meteo.com/) as `.om` files: one dataset per variable and weather
model, in an *Open-Meteo forecast* subcategory of each thematic category. They need a
GeoManager with the `OpenMeteoLayer` model (`openmeteo` layer type), and a MapViewer
rendering them with
[`@openmeteo/weather-map-layer`](https://github.com/open-meteo/weather-map-layer).

Unlike the other entries they are not selected when first loaded: pick the ones to
provision in the tree. Only the global models are listed. The script can add the
regional ones (Europe, North America, Japan…) with `--regional`: they carry their
footprint and are only loaded when they cover the configured country.

These datasets are generated: `scripts/openmeteo_catalog.mjs` reads the weather models,
variables, labels and footprints from the npm package, checks which variables the latest
run of each model provides, and rewrites them in `catalog.json` (the rest of the file is
left as is). Rerun it when Open-Meteo adds models or variables:

```shell
npm install --no-save @openmeteo/weather-map-layer@0.3.0
node scripts/openmeteo_catalog.mjs              # --dry-run to only print the counts
```

or point it at the package installed in a MapViewer checkout with
`--package ../geomapviewer/node_modules/@openmeteo/weather-map-layer`.

## Development

```shell
pip install -e ".[boundaries]"
```

`boot_django.py` configures a minimal Django for the helper scripts (point it at a
PostGIS database with the `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` env vars):

```shell
python makemigrations.py
python migrate.py
python -m build          # builds dist/*.whl and dist/*.tar.gz
```

Translations live in `dataset_helper/locale/` (ar, es, fr, pt):

```shell
django-admin makemessages -l fr
django-admin compilemessages
```

Releases are published to PyPI by `.github/workflows/publish.yml` when a GitHub release
is created (trusted publishing — no token needed).

## License

MIT — see [LICENSE](LICENSE).
