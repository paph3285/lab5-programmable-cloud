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
SOURCE_INSTANCE = "lab5-part1-vm"

SNAPSHOT_NAME = f"base-snapshot-{SOURCE_INSTANCE}"
IMAGE_NAME = f"base-image-{SOURCE_INSTANCE}"

CLONE_NAMES = [
    f"clone-1-{SOURCE_INSTANCE}",
    f"clone-2-{SOURCE_INSTANCE}",
    f"clone-3-{SOURCE_INSTANCE}",
]

MACHINE_TYPE = "e2-medium"
NETWORK_TAGS = ["allow-5000", "allow-ssh"]  # keep access consistent
TIMING_FILE = "TIMING.md"


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


def snapshot_exists(compute, project, snapshot_name):
    try:
        compute.snapshots().get(project=project, snapshot=snapshot_name).execute()
        return True
    except googleapiclient.errors.HttpError as e:
        if e.resp.status == 404:
            return False
        raise


def image_exists(compute, project, image_name):
    try:
        compute.images().get(project=project, image=image_name).execute()
        return True
    except googleapiclient.errors.HttpError as e:
        if e.resp.status == 404:
            return False
        raise


def instance_exists(compute, project, zone, name):
    try:
        compute.instances().get(project=project, zone=zone, instance=name).execute()
        return True
    except googleapiclient.errors.HttpError as e:
        if e.resp.status == 404:
            return False
        raise


def get_boot_disk_name(compute, project, zone, instance_name):
    inst = compute.instances().get(project=project, zone=zone, instance=instance_name).execute()
    for d in inst.get("disks", []):
        if d.get("boot"):
            return d["source"].split("/")[-1]
    raise RuntimeError("Could not find boot disk on instance")


def create_snapshot_from_disk(compute, project, zone, disk_name, snapshot_name):
    body = {"name": snapshot_name}
    op = compute.disks().createSnapshot(project=project, zone=zone, disk=disk_name, body=body).execute()
    wait_for_zone_op(compute, project, zone, op["name"])


def create_image_from_snapshot(compute, project, image_name, snapshot_name):
    body = {
        "name": image_name,
        "sourceSnapshot": f"global/snapshots/{snapshot_name}",
    }
    op = compute.images().insert(project=project, body=body).execute()
    wait_for_global_op(compute, project, op["name"])


def create_instance_from_image(compute, project, zone, name, image_name):
    body = {
        "name": name,
        "machineType": f"zones/{zone}/machineTypes/{MACHINE_TYPE}",
        "disks": [{
            "boot": True,
            "autoDelete": True,
            "initializeParams": {
                "sourceImage": f"global/images/{image_name}",
            },
        }],
        "networkInterfaces": [{
            "network": "global/networks/default",
            "accessConfigs": [{"name": "External NAT", "type": "ONE_TO_ONE_NAT"}],
        }],
        "tags": {"items": NETWORK_TAGS},
    }

    start = time.time()
    op = compute.instances().insert(project=project, zone=zone, body=body).execute()
    wait_for_zone_op(compute, project, zone, op["name"])
    end = time.time()
    return end - start


def get_external_ip(compute, project, zone, name):
    inst = compute.instances().get(project=project, zone=zone, instance=name).execute()
    ni = inst.get("networkInterfaces", [])
    if not ni:
        return None
    ac = ni[0].get("accessConfigs", [])
    if not ac:
        return None
    return ac[0].get("natIP")


def write_timing_md(rows):
    # rows: list of (instance_name, seconds, ip)
    with open(TIMING_FILE, "w") as f:
        f.write("# VM Creation Timing (Part 2)\n\n")
        f.write(f"- Source instance: `{SOURCE_INSTANCE}`\n")
        f.write(f"- Snapshot: `{SNAPSHOT_NAME}`\n")
        f.write(f"- Image: `{IMAGE_NAME}`\n")
        f.write(f"- Zone: `{ZONE}`\n\n")
        f.write("| Instance | Create time (seconds) | External IP |\n")
        f.write("|---|---:|---|\n")
        for name, secs, ip in rows:
            f.write(f"| `{name}` | {secs:.2f} | `{ip or ''}` |\n")


def main():
    # Ensure snapshot exists
    if not snapshot_exists(service, project, SNAPSHOT_NAME):
        boot_disk = get_boot_disk_name(service, project, ZONE, SOURCE_INSTANCE)
        print(f"Boot disk for {SOURCE_INSTANCE}: {boot_disk}")
        print(f"Creating snapshot: {SNAPSHOT_NAME} ...")
        create_snapshot_from_disk(service, project, ZONE, boot_disk, SNAPSHOT_NAME)
        print("Snapshot created.")
    else:
        print(f"Snapshot already exists: {SNAPSHOT_NAME}")

    # Ensure image exists
    if not image_exists(service, project, IMAGE_NAME):
        print(f"Creating image: {IMAGE_NAME} from snapshot {SNAPSHOT_NAME} ...")
        create_image_from_snapshot(service, project, IMAGE_NAME, SNAPSHOT_NAME)
        print("Image created.")
    else:
        print(f"Image already exists: {IMAGE_NAME}")

    # Create 3 instances from image, timing each creation
    rows = []
    for name in CLONE_NAMES:
        if instance_exists(service, project, ZONE, name):
            ip = get_external_ip(service, project, ZONE, name)
            print(f"Instance already exists: {name} (ip={ip})")
            rows.append((name, 0.0, ip))
            continue

        print(f"Creating instance from image: {name} ...")
        secs = create_instance_from_image(service, project, ZONE, name, IMAGE_NAME)
        ip = get_external_ip(service, project, ZONE, name)
        print(f"Created {name} in {secs:.2f} seconds (ip={ip})")
        rows.append((name, secs, ip))

    write_timing_md(rows)
    print(f"\nWrote {TIMING_FILE}\n")


if __name__ == "__main__":
    main()
