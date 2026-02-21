#!/usr/bin/env python3

import argparse
import os
import time
import base64

import googleapiclient.discovery
import google.oauth2.service_account as service_account
from googleapiclient.errors import HttpError


# -------------------------
# Build Compute Engine API client using a service account key
# -------------------------
def build_compute_service(creds_path: str):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    return googleapiclient.discovery.build("compute", "v1", credentials=creds)


# -------------------------
# Wait for zonal operation to finish
# -------------------------
def wait_for_zone_operation(compute, project: str, zone: str, operation_name: str, poll_seconds: int = 2):
    while True:
        op = compute.zoneOperations().get(project=project, zone=zone, operation=operation_name).execute()
        if op.get("status") == "DONE":
            if "error" in op:
                raise RuntimeError(op["error"])
            return op
        time.sleep(poll_seconds)


# -------------------------
# Read file helper
# -------------------------
def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# -------------------------
# Instance exists?
# -------------------------
def instance_exists(compute, project: str, zone: str, name: str) -> bool:
    try:
        compute.instances().get(project=project, zone=zone, instance=name).execute()
        return True
    except HttpError as e:
        if getattr(e, "resp", None) is not None and e.resp.status == 404:
            return False
        raise


# -------------------------
# Create VM-1
# -------------------------
def create_vm1(
    compute,
    project,
    zone,
    name,
    machine_type,
    source_image,
    vm1_startup,
    vm2_startup,
    vm1_launch_code,
    service_creds_b64,
):
    metadata_items = [
        {"key": "startup-script", "value": vm1_startup},
        {"key": "vm2-startup-script", "value": vm2_startup},
        {"key": "vm1-launch-vm2-code", "value": vm1_launch_code},
        {"key": "service-credentials-b64", "value": service_creds_b64},
        {"key": "project", "value": project},
        {"key": "zone", "value": zone},
        {"key": "vm2-name", "value": "lab5-vm2-flask"},
    ]

    body = {
        "name": name,
        "machineType": f"zones/{zone}/machineTypes/{machine_type}",
        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {"sourceImage": source_image},
            }
        ],
        "networkInterfaces": [
            {
                "network": "global/networks/default",
                "accessConfigs": [{"name": "External NAT", "type": "ONE_TO_ONE_NAT"}],
            }
        ],
        "metadata": {"items": metadata_items},
        "tags": {"items": ["allow-ssh"]},
    }

    op = compute.instances().insert(project=project, zone=zone, body=body).execute()
    wait_for_zone_operation(compute, project, zone, op["name"])


# -------------------------
# CLI
# -------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Lab5 Part3: VM1 launches VM2 using service account + metadata")
    p.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--zone", default="us-west1-b")
    p.add_argument("--creds", default="service-credentials.json")

    p.add_argument("--vm1-name", default="lab5-vm1-launcher")
    p.add_argument("--machine-type", default="e2-medium")
    p.add_argument("--image", default="projects/debian-cloud/global/images/family/debian-12")

    p.add_argument("--vm1-startup", default="vm1-startup-script.sh")
    p.add_argument("--vm2-startup", default="vm2-startup-script.sh")
    p.add_argument("--vm1-launch", default="vm1-launch-vm2.py")

    p.add_argument("--recreate", action="store_true")
    return p.parse_args()


# -------------------------
# MAIN
# -------------------------
def main():
    args = parse_args()

    if not args.project:
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT or pass --project")

    compute = build_compute_service(args.creds)

    vm1_startup = read_text(args.vm1_startup)
    vm2_startup = read_text(args.vm2_startup)
    vm1_launch_code = read_text(args.vm1_launch)

    # Base64 encode service account JSON
    with open(args.creds, "rb") as f:
        service_creds_b64 = base64.b64encode(f.read()).decode("utf-8")

    if instance_exists(compute, args.project, args.zone, args.vm1_name):
        if args.recreate:
            print("Deleting existing VM-1...")
            op = compute.instances().delete(
                project=args.project, zone=args.zone, instance=args.vm1_name
            ).execute()
            wait_for_zone_operation(compute, args.project, args.zone, op["name"])
        else:
            print("VM-1 already exists. Use --recreate to rebuild.")
            return

    print(f"Creating VM-1: {args.vm1_name}")

    create_vm1(
        compute,
        args.project,
        args.zone,
        args.vm1_name,
        args.machine_type,
        args.image,
        vm1_startup,
        vm2_startup,
        vm1_launch_code,
        service_creds_b64,
    )

    print("VM-1 created.")
    print("SSH and check logs:")
    print(f"gcloud compute ssh {args.vm1_name} --zone {args.zone}")


if __name__ == "__main__":
    main()
