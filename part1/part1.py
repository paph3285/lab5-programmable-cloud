#!/usr/bin/env python3

import argparse
import os
import time
from pprint import pprint

import googleapiclient.discovery
import googleapiclient.errors
import google.auth

credentials, project = google.auth.default()
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

ZONE = "us-west1-b"
INSTANCE_NAME = "lab5-part1-vm"
FIREWALL_RULE_NAME = "allow-5000"
NETWORK_TAG = "allow-5000"
PORT = "5000"

# Use e2-medium while developing; change to f1-micro before final if desired
MACHINE_TYPE = "e2-medium"

STARTUP_SCRIPT = r"""#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/startup-script.log) 2>&1

mkdir -p /opt/lab5
cd /opt/lab5

apt-get update
apt-get install -y python3 python3-pip git

if [ ! -d flask-tutorial ]; then
  git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
fi

cd flask-tutorial
python3 setup.py install
pip3 install -e .

export FLASK_APP=flaskr
flask init-db
nohup flask run -h 0.0.0.0 -p 5000 > /var/log/flaskr.log 2>&1 &
"""

#
# (kept) lists all instances
#
def list_instances(compute, project, zone):
    result = compute.instances().list(project=project, zone=zone).execute()
    return result['items'] if 'items' in result else None

def wait_for_zone_op(compute, project, zone, op_name):
    while True:
        op = compute.zoneOperations().get(project=project, zone=zone, operation=op_name).execute()
        if op.get("status") == "DONE":
            if "error" in op:
                raise RuntimeError(op["error"])
            return
        time.sleep(2)

def wait_for_global_op(compute, project, op_name):
    while True:
        op = compute.globalOperations().get(project=project, operation=op_name).execute()
        if op.get("status") == "DONE":
            if "error" in op:
                raise RuntimeError(op["error"])
            return
        time.sleep(2)

def firewall_rule_exists(compute, project, name):
    try:
        compute.firewalls().get(project=project, firewall=name).execute()
        return True
    except googleapiclient.errors.HttpError as e:
        if e.resp.status == 404:
            return False
        raise

def ensure_firewall_rule_allow_5000(compute, project):
    if firewall_rule_exists(compute, project, FIREWALL_RULE_NAME):
        return

    body = {
        "name": FIREWALL_RULE_NAME,
        "network": "global/networks/default",
        "direction": "INGRESS",
        "sourceRanges": ["0.0.0.0/0"],
        "allowed": [{"IPProtocol": "tcp", "ports": [PORT]}],
        "targetTags": [NETWORK_TAG],
        "description": "Allow inbound TCP 5000 for Lab5 Part1",
    }

    op = compute.firewalls().insert(project=project, body=body).execute()
    wait_for_global_op(compute, project, op["name"])

def instance_exists(compute, project, zone, name):
    try:
        compute.instances().get(project=project, zone=zone, instance=name).execute()
        return True
    except googleapiclient.errors.HttpError as e:
        if e.resp.status == 404:
            return False
        raise

def get_ubuntu_2204_image_selflink(compute):
    img = compute.images().getFromFamily(project="ubuntu-os-cloud", family="ubuntu-2204-lts").execute()
    return img["selfLink"]

def create_instance(compute, project, zone, name):
    source_image = get_ubuntu_2204_image_selflink(compute)

    config = {
        "name": name,
        "machineType": f"zones/{zone}/machineTypes/{MACHINE_TYPE}",
        "disks": [{
            "boot": True,
            "autoDelete": True,
            "initializeParams": {"sourceImage": source_image},
        }],
        "networkInterfaces": [{
            "network": "global/networks/default",
            "accessConfigs": [{"name": "External NAT", "type": "ONE_TO_ONE_NAT"}],
        }],
        "tags": {"items": [NETWORK_TAG]},
        "metadata": {"items": [{"key": "startup-script", "value": STARTUP_SCRIPT}]},
    }

    op = compute.instances().insert(project=project, zone=zone, body=config).execute()
    wait_for_zone_op(compute, project, zone, op["name"])

def get_external_ip(compute, project, zone, name):
    inst = compute.instances().get(project=project, zone=zone, instance=name).execute()
    ni = inst.get("networkInterfaces", [])
    if not ni:
        return None
    ac = ni[0].get("accessConfigs", [])
    if not ac:
        return None
    return ac[0].get("natIP")

def main():
    # Create firewall rule (once)
    ensure_firewall_rule_allow_5000(service, project)

    # Create instance if missing
    if not instance_exists(service, project, ZONE, INSTANCE_NAME):
        create_instance(service, project, ZONE, INSTANCE_NAME)

    # Print URL
    ip = get_external_ip(service, project, ZONE, INSTANCE_NAME)
    print(f"\nVisit: http://{ip}:5000\n")

if __name__ == "__main__":
    main()
