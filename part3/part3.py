#!/usr/bin/env python3

import argparse
import os
import time
from typing import List, Tuple, Optional

import googleapiclient.discovery
import google.oauth2.service_account as service_account
from googleapiclient.errors import HttpError


# ----------------------------
# Build Compute Engine API client
# ----------------------------
def build_compute_service(creds_path: str):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    return googleapiclient.discovery.build("compute", "v1", credentials=creds)


# ----------------------------
# Operation helper
# ----------------------------
def wait_for_zone_operation(compute, project: str, zone: str, operation_name: str, poll_seconds: int = 2):
    """Poll a zonal operation until it finishes (DONE)."""
    while True:
        op = compute.zoneOperations().get(project=project, zone=zone, operation=operation_name).execute()

        if op.get("status") == "DONE":
            if "error" in op:
                raise RuntimeError(op["error"])
            return op

        time.sleep(poll_seconds)


# ----------------------------
# Instance helpers
# ----------------------------
def list_instances(compute, project: str, zone: str):
    """Return a list of instance resource dicts (possibly empty)."""
    resp = compute.instances().list(project=project, zone=zone).execute()
    return resp.get("items", [])


def get_instance(compute, project: str, zone: str, name: str):
    """Fetch one instance resource dict."""
    return compute.instances().get(project=project, zone=zone, instance=name).execute()


def instance_exists(compute, project: str, zone: str, name: str) -> bool:
    """
    Return True if instance exists, False if 404.
    IMPORTANT: only 404 means "missing"; other errors should raise.
    """
    try:
        compute.instances().get(project=project, zone=zone, instance=name).execute()
        return True
    except HttpError as e:
        if getattr(e, "resp", None) is not None and e.resp.status == 404:
            return False
        raise


def get_instance_tags(compute, project: str, zone: str, name: str) -> List[str]:
    """Return tag list for an instance (possibly empty)."""
    inst = get_instance(compute, project, zone, name)
    return inst.get("tags", {}).get("items", [])


# ----------------------------
# Base instance config extraction 
# ----------------------------
def get_base_instance_config(
    compute, project: str, zone: str, base_instance: str
) -> Tuple[str, Optional[str], Optional[str], str]:
    """
    Extract minimal config from the base instance to create clones:
      - machineType
      - network + subnetwork
      - boot disk sourceImage (fallback to Debian 12 if missing)
    """
    inst = get_instance(compute, project, zone, base_instance)

    machine_type = inst["machineType"]

    net = inst["networkInterfaces"][0]
    network = net.get("network")
    subnetwork = net.get("subnetwork")

    boot_disk = None
    for d in inst.get("disks", []):
        if d.get("boot"):
            boot_disk = d
            break
    if not boot_disk:
        raise RuntimeError("Base instance has no boot disk (unexpected).")

    init_params = boot_disk.get("initializeParams", {})
    source_image = init_params.get("sourceImage")

    # Fallback if sourceImage not present (some instances won’t have it on GET)
    if not source_image:
        source_image = "projects/debian-cloud/global/images/family/debian-12"

    return machine_type, network, subnetwork, source_image


# ----------------------------
# Create instance 
# ----------------------------
def create_instance(
    compute,
    project: str,
    zone: str,
    name: str,
    machine_type: str,
    network: Optional[str],
    subnetwork: Optional[str],
    source_image: str,
    tags: List[str],
    external_ip: bool,
):
    """
    Create a VM instance.

    NOTE: This creates a NEW boot disk from source_image (not a snapshot clone).
    """
    nic = {
        "network": network,
        "subnetwork": subnetwork,
    }

    # External IP toggle:
    # - If external_ip=True, attach ONE_TO_ONE_NAT (consumes IN_USE_ADDRESSES quota)
    # - If external_ip=False, don't attach accessConfigs (internal-only)
    if external_ip:
        nic["accessConfigs"] = [{"name": "External NAT", "type": "ONE_TO_ONE_NAT"}]

    body = {
        "name": name,
        "machineType": machine_type,
        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {"sourceImage": source_image},
            }
        ],
        "networkInterfaces": [nic],
    }

    if tags:
        body["tags"] = {"items": tags}

    try:
        op = compute.instances().insert(project=project, zone=zone, body=body).execute()
        wait_for_zone_operation(compute, project, zone, op["name"])
        return True
    except HttpError as e:
        # If instance already exists, don't crash the whole run.
        if getattr(e, "resp", None) is not None and e.resp.status == 409:
            print(f"Already exists (409), skipping: {name}")
            return False
        raise


# ----------------------------
# CLI args
# ----------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Lab 5 Part 3: Use Python + Compute Engine API to manage instances."
    )

    p.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--zone", default="us-west1-b")
    p.add_argument("--creds", default="service-credentials.json")

    p.add_argument("--base", default="lab5-part1-vm", help="Base instance to copy config from")
    p.add_argument("--prefix", default="clone", help="Prefix for clone names")
    p.add_argument("--count", type=int, default=3, help="Number of clones to create")

    p.add_argument("--create", action="store_true", help="Actually create instances")
    p.add_argument("--skip-existing", action="store_true", help="Skip clones that already exist")

    # Quota-safe option
    p.add_argument(
        "--external-ip",
        dest="external_ip",
        action="store_true",
        help="Attach an external IP to each clone (uses IN_USE_ADDRESSES quota).",
    )
    p.add_argument(
        "--no-external-ip",
        dest="external_ip",
        action="store_false",
        help="Do NOT attach external IPs to clones (internal-only).",
    )
    p.set_defaults(external_ip=True)

    return p.parse_args()


# ----------------------------
# main
# ----------------------------
def main():
    args = parse_args()

    if not args.project:
        raise SystemExit("ERROR: Set GOOGLE_CLOUD_PROJECT or pass --project")

    compute = build_compute_service(args.creds)

    print(f"Project: {args.project}")
    print(f"Zone:    {args.zone}")

    print("\nCurrent instances:")
    for inst in list_instances(compute, args.project, args.zone):
        print(f" - {inst['name']}")

    if not args.create:
        print("\nNothing created. (Run with --create to create clones.)")
        return

    machine_type, network, subnetwork, source_image = get_base_instance_config(
        compute, args.project, args.zone, args.base
    )
    base_tags = get_instance_tags(compute, args.project, args.zone, args.base)

    print("\nBase config:")
    print(f" - base:        {args.base}")
    print(f" - machineType: {machine_type}")
    print(f" - sourceImage: {source_image}")
    print(f" - tags:        {base_tags}")
    print(f" - external_ip: {args.external_ip}")

    created_any = False

    for i in range(1, args.count + 1):
        name = f"{args.prefix}-{i}-{args.base}"

        if args.skip_existing and instance_exists(compute, args.project, args.zone, name):
            print(f"\nSkipping existing: {name}")
            continue

        print(f"\nCreating: {name}")
        did_create = create_instance(
            compute=compute,
            project=args.project,
            zone=args.zone,
            name=name,
            machine_type=machine_type,
            network=network,
            subnetwork=subnetwork,
            source_image=source_image,
            tags=base_tags,
            external_ip=args.external_ip,
        )
        if did_create:
            print(f"Created: {name}")
            created_any = True

    print("\nUpdated instances:")
    for inst in list_instances(compute, args.project, args.zone):
        print(f" - {inst['name']}")

    if not created_any:
        print("\n(No new instances were created.)")


if __name__ == "__main__":
    main()
