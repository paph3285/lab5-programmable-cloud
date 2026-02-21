#!/usr/bin/env python3


import argparse
import os
import time

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
# Read a local file as text
# -------------------------
def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# -------------------------
# Does an instance exist?
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
# Create VM-1 (launcher VM)
# -------------------------
def create_vm1(
    compute,
    project: str,
    zone: str,
    name: str,
    machine_type: str,
    source_image: str,
    startup_script_vm1: str,
    vm2_startup_script: str,
    vm1_launch_code: str,
    service_creds_json: str,
):
    # NOTE: We pass *multiple* metadata items to VM-1.
    # VM-1's startup script will curl these from metadata server.
    metadata_items = [
        {"key": "startup-script", "value": startup_script_vm1},  # VM-1 startup script
        {"key": "vm2-startup-script", "value": vm2_startup_script},
        {"key": "vm1-launch-vm2-code", "value": vm1_launch_code},
        {"key": "service-credentials", "value": service_creds_json},
        {"key": "project", "value": project},
        {"key": "zone", "value": zone},
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
                # VM-1 needs SSH access for debugging; external NAT is fine.
                "accessConfigs": [{"name": "External NAT", "type": "ONE_TO_ONE_NAT"}],
            }
        ],
        "metadata": {"items": metadata_items},
        "tags": {"items": ["allow-ssh"]},
    }

    op = compute.instances().insert(project=project, zone=zone, body=body).execute()
    wait_for_zone_operation(compute, project, zone, op["name"])


def parse_args():
    p = argparse.ArgumentParser(description="Lab 5 Part 3: Create VM-1 that launches VM-2 using metadata + service account.")
    p.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="GCP project id")
    p.add_argument("--zone", default="us-west1-b", help="Zone")
    p.add_argument("--creds", default="service-credentials.json", help="Service account JSON key path")

    # VM-1 instance settings
    p.add_argument("--vm1-name", default="lab5-vm1-launcher", help="Name for VM-1")
    p.add_argument("--machine-type", default="e2-medium", help="Machine type name (e.g. e2-medium)")
    p.add_argument("--image", default="projects/debian-cloud/global/images/family/debian-12", help="Boot image for VM-1")

    # Local files to embed in metadata
    p.add_argument("--vm1-startup", default="vm1-startup-script.sh", help="VM-1 startup script file")
    p.add_argument("--vm2-startup", default="vm2-startup-script.sh", help="VM-2 startup script file")
    p.add_argument("--vm1-launch", default="vm1-launch-vm2.py", help="VM-1 python launcher file")

    # behavior
    p.add_argument("--recreate", action="store_true", help="If set, delete existing VM-1 and recreate it (optional).")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.project:
        raise SystemExit("ERROR: Set GOOGLE_CLOUD_PROJECT or pass --project")

    compute = build_compute_service(args.creds)

    # Read files we will embed into VM-1 metadata
    vm1_startup_script = read_text(args.vm1_startup)
    vm2_startup_script = read_text(args.vm2_startup)
    vm1_launch_code = read_text(args.vm1_launch)
    service_creds_json = read_text(args.creds)

    # If VM-1 already exists, do NOT blindly recreate unless user asked
    if instance_exists(compute, args.project, args.zone, args.vm1_name):
        if args.recreate:
            print(f"VM-1 {args.vm1_name} exists; deleting (recreate requested)...")
            op = compute.instances().delete(project=args.project, zone=args.zone, instance=args.vm1_name).execute()
            wait_for_zone_operation(compute, args.project, args.zone, op["name"])
        else:
            print(f"VM-1 {args.vm1_name} already exists. (Not changing it.)")
            print("If you want to rebuild VM-1 with new metadata, rerun with --recreate")
            return

    print(f"Creating VM-1: {args.vm1_name} in {args.zone} (project {args.project})")
    create_vm1(
        compute=compute,
        project=args.project,
        zone=args.zone,
        name=args.vm1_name,
        machine_type=args.machine_type,
        source_image=args.image,
        startup_script_vm1=vm1_startup_script,
        vm2_startup_script=vm2_startup_script,
        vm1_launch_code=vm1_launch_code,
        service_creds_json=service_creds_json,
    )

    print("Done. VM-1 created.")
    print("Next: SSH into VM-1 and check logs to confirm it launched VM-2.")
    print("Example: gcloud compute ssh lab5-vm1-launcher --zone us-west1-b")


if __name__ == "__main__":
    main()
