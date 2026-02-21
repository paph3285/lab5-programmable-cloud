#!/bin/bash
set -euxo pipefail

apt-get update
apt-get install -y curl python3-venv python3-pip

python3 -m venv /srv/venv
/srv/venv/bin/pip install --upgrade pip
/srv/venv/bin/pip install google-api-python-client google-auth google-auth-httplib2

mkdir -p /srv
cd /srv

# Pull metadata
curl -sS http://metadata/computeMetadata/v1/instance/attributes/service-credentials-b64 \
  -H "Metadata-Flavor: Google" > service-credentials.b64

curl -sS http://metadata/computeMetadata/v1/instance/attributes/vm2-startup-script \
  -H "Metadata-Flavor: Google" > vm2-startup-script.sh
chmod +x vm2-startup-script.sh

curl -sS http://metadata/computeMetadata/v1/instance/attributes/vm1-launch-vm2-code \
  -H "Metadata-Flavor: Google" > vm1-launch-vm2.py
chmod +x vm1-launch-vm2.py

PROJECT=$(curl -sS http://metadata/computeMetadata/v1/instance/attributes/project -H "Metadata-Flavor: Google")
ZONE=$(curl -sS http://metadata/computeMetadata/v1/instance/attributes/zone -H "Metadata-Flavor: Google")
VM2_NAME=$(curl -sS http://metadata/computeMetadata/v1/instance/attributes/vm2-name -H "Metadata-Flavor: Google")

export PROJECT ZONE VM2_NAME
export VM2_STARTUP=/srv/vm2-startup-script.sh

/srv/venv/bin/python3 /srv/vm1-launch-vm2.py | tee /var/log/vm1-launch.log
