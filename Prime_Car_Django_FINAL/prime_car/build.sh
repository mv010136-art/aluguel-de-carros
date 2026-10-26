#!/usr/bin/env bash
# Comando de build da hospedagem (Render). Falha imediatamente em qualquer erro.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py clearsessions
