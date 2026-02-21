#!/bin/bash
set -euxo pipefail

apt-get update
apt-get install -y git curl python3-pip python3-venv

mkdir -p /opt/lab5
cd /opt/lab5

python3 -m venv /opt/lab5/venv
/opt/lab5/venv/bin/pip install --upgrade pip

# Course Flask tutorial repo
if [ ! -d flask-tutorial ]; then
  git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial.git flask-tutorial
fi

cd flask-tutorial

# Find where the Flask tutorial app actually lives in THIS repo
APP_DIR=""
if [ -f "setup.py" ] || [ -f "pyproject.toml" ]; then
  APP_DIR="."
elif [ -d "tutorial" ] && [ -f "tutorial/__init__.py" ]; then
  APP_DIR="."
else
  # common fallback: search for the Flask tutorial package (flaskr)
  APP_DIR="$(dirname "$(find . -maxdepth 4 -type f -name 'flaskr' -o -name 'flaskr.py' 2>/dev/null | head -n 1)")" || true
fi

# If still empty, just use repo root and let pip error clearly
if [ -z "${APP_DIR}" ]; then
  APP_DIR="."
fi

cd "$APP_DIR"

/opt/lab5/venv/bin/pip install -e .

export FLASK_APP=flaskr
/opt/lab5/venv/bin/flask init-db

mkdir -p /var/log
nohup /opt/lab5/venv/bin/flask run -h 0.0.0.0 -p 5000 >/var/log/flaskr.log 2>&1 &
