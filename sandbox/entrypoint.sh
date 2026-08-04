#!/bin/bash
set -euo pipefail

echo "Waiting for the database..."
until python3 -c "
import os, sys, psycopg2
from urllib.parse import urlparse
u = urlparse(os.environ['DATABASE_URL'])
try:
    psycopg2.connect(dbname=u.path[1:], user=u.username, password=u.password,
                     host=u.hostname, port=u.port or 5432).close()
except Exception as e:
    print(e, file=sys.stderr); sys.exit(1)
" 2>/dev/null; do
  sleep 1
done
echo "Database is up."

# Note the app label, not the module name.
python3 manage.py migrate --noinput

if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
  python3 manage.py createsuperuser --noinput 2>/dev/null \
    && echo "Created superuser $DJANGO_SUPERUSER_USERNAME." \
    || echo "Superuser $DJANGO_SUPERUSER_USERNAME already exists."
fi

echo "Dataset Helper sandbox: http://localhost:8000/admin/geomanager/dataset_helper/"
exec python3 manage.py runserver 0.0.0.0:8000
