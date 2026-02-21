#!/usr/bin/env python3
import base64
import os
import time
import googleapiclient.discovery
import google.oauth2.service_account as service_account

def wait_for_zone_op(compute, project, zone, op_name):
    while True:
        op = compute.zoneOperations().get(project=project, zone=zone, operation=op_name).execute()
        if op.get("status") == "DONE":
            if "error" in op:
                raise RuntimeError(op["error"])
            return
        time.sleep(2)

def main():
    project = os.environ["PROJECT"]
    zone = os.environ["ZONE"]
    vm2_name = os.environ["VM2_NAME"]
    vm2_startup_path = os.environ["VM2_STARTUP"]

    with open("/srv/service-credentials.b64", "r") as f:
        b64 = f.read().strip()
    creds_json = base64.b64decode(b64.encode("utf-8"))
    with open("/srv/service-credentials.json", "wb") as f:
        f.write(creds_json)

    creds = service_account.Credentials.from_service_account_file("/srv/service-credentials.json")
    compute = googleapiclient.discovery.build("compute", "v1", credentials=creds)

    # Read VM-2 startup script
    with open(vm2_startup_path, "r") as f:
        vm2_startup = f.read()

    # If VM-2 already exists, just print and exit
    try:
        compute.instances().get(project=project, zone=zone, instance=vm2_name).execute()
        print(f"VM-2 already exists: {vm2_name}")
        return
    except Exception:
        pass

    machine_type = f"zones/{zone}/machineTypes/e2-micro"
    source_image = "projects/debian-cloud/global/images/family/debian-12"

    config = {
        "name": vm2_name,
        "machineType": machine_type,
        "disks": [{
            "boot": True,
            "autoDelete": True,
            "initializeParams": {"sourceImage": source_image}
        }],
        "networkInterfaces": [{
            "network": "global/networks/default",
            "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}]
        }],
        "tags": {"items": ["allow-5000", "allow-ssh"]},
        "metadata": {"items": [{"key": "startup-script", "value": vm2_startup}]}
    }

    op = compute.instances().insert(project=project, zone=zone, body=config).execute()
    wait_for_zone_op(compute, project, zone, op["name"])

    inst = compute.instances().get(project=project, zone=zone, instance=vm2_name).execute()
    ip = inst["networkInterfaces"][0]["accessConfigs"][0]["natIP"]
    print(f"Created VM-2: {vm2_name} (ip={ip})")
    print(f"Visit: http://{ip}:5000")

if __name__ == "__main__":
    main()
