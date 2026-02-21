#!/usr/bin/env python3

import argparse
import os
import time

import googleapiclient.discovery
import google.oauth2.service_account as service_account


def build_compute_service(creds_path: str):
    creds = service_account.Credentials.from_service_account_file(creds_path)
    return googleapiclient.discovery.build("compute", "v1", credentials=creds)


def wait_for_zone_operation(compute, project: str, zone: str, operation_name: str, poll_seconds: int = 2):
    """Poll a zonal operation until it finishes."""
    while True:
        op = compute.zoneOperations().get(
            project=project, zone=zone, operation=operation_name
        ).execute()

        if op.get("status") == "DONE":
            if "error" in op:
                raise RuntimeError(op["error"])
            return op

        time.sleep(poll_seconds)


def list_instances(compute, project: str, zone: str):
    """Return a list of instance resource dicts."""
    resp = compute.instances().list(project=project, zone=zone).execute()
    return resp.get("items", [])


def get_instance(compute, project: str, zone: str, name: str):
    return compute.instances().get(project=project, zone=zone, instance=name).execute()


def get_base_instance_config(compute, project: str, zone: str, base_instance: str):
    """
    Extract minimal info from a base instance to make clones:
    - machine type
    - network/subnetwork
    - boot disk source image (fallback to Debian 12 if unavailable)
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
        raise RuntimeError("Base instance has no boot disk?")

    init_params = boot_disk.get("initializeParams", {})
    source_image = init_params.get("sourceImage")

    # Fallback if sourceImage not present
    if not source_image:
        source_image = "projects/debian-cloud/global/images/family/debian-12"

    return machine_type, network, subnetwork, source_image


def instance_exists(compute, project: str, zone: str, name: str) -> bool:
    try:
        _ = get_instance(compute, project, zone, name)
        return True
    except Exception:
        return False


def create_instance(
    compute,
    project: str,
    zone: str,
    name: str,
    machine_type: str,
    network: str,
    subnetwork: str,
    source_image: str,
    tags: list[str],
):
    """
    Create a VM instance.
    Note: This creates a new boot disk from source_image (not a full disk clone/snapshot).
    For this lab, that's usually acceptable unless your instructions explicitly require snapshots.
    """
    body = {
        "name": name,
        "machineType": machine_type,
        "tags": {"items": tags} if tags else None,
        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": source_image,
                },
            }
        ],
        "networkInterfaces": [
            {
                "network": network,
                "subnetwork": subnetwork,
                "accessConfigs": [{"name": "External NAT", "type": "ONE_TO_ONE_NAT"}],
            }
        ],
    }

    # remove None fields (Compute API can be picky)
    if body["tags"] is None:
        body.pop("tags", None)

    op = compute.instances().insert(project=project, zone=zone, body=body).execute()
    wait_for_zone_operation(compute, project, zone, op["name"])
    return op


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

    return p.parse_args()


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

    print("\nBase config:")
    print(f" - base:         {args.base}")
    print(f" - machineType:  {machine_type}")
    print(f" - sourceImage:  {source_image}")

    for i in range(1, args.count + 1):
        name = f"{args.prefix}-{i}-{args.base}"

        if args.skip_existing and instance_exists(compute, args.project, args.zone, name):
            print(f"\nSkipping existing: {name}")
            continue

        print(f"\nCreating: {name}")
        create_instance(
            compute=compute,
            project=args.project,
            zone=args.zone,
            name=name,
            machine_type=machine_type,
            network=network,
            subnetwork=subnetwork,
            source_image=source_image,
            tags=["allow-ssh"],  # add tags if your lab requires them
        )
        print(f"Created: {name}")

    print("\nUpdated instances:")
    for inst in list_instances(compute, args.project, args.zone):
        print(f" - {inst['name']}")


if __name__ == "__main__":
    main()
