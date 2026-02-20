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

def main():
    # Ensure snapshot exists (create if missing)
    if not snapshot_exists(service, project, SNAPSHOT_NAME):
        boot_disk = get_boot_disk_name(service, project, ZONE, SOURCE_INSTANCE)
        print(f"Boot disk for {SOURCE_INSTANCE}: {boot_disk}")
        print(f"Creating snapshot: {SNAPSHOT_NAME} ...")
        create_snapshot_from_disk(service, project, ZONE, boot_disk, SNAPSHOT_NAME)
        print("Snapshot created.")
    else:
        print(f"Snapshot already exists: {SNAPSHOT_NAME}")

    # Create image from snapshot (Part 2 requirement)
    if image_exists(service, project, IMAGE_NAME):
        print(f"Image already exists: {IMAGE_NAME}")
        return

    print(f"Creating image: {IMAGE_NAME} from snapshot {SNAPSHOT_NAME} ...")
    create_image_from_snapshot(service, project, IMAGE_NAME, SNAPSHOT_NAME)
    print("Image created.")

if __name__ == "__main__":
    main()
