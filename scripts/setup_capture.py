#!/usr/bin/env python3
"""Prepares vCenter for packet captures (docs/admin-guide.md, "Packet capture"). Run it once, like
setup_vcenter.py (same sign-in, same options), before building the capture appliance:

    ~/labdeploy-setup/bin/python scripts/setup_capture.py

It:

  1. adds the capture port group (default "LAN-capture") on every host's standard vSwitch that
     carries the LAN's port group, with the LAN's VLAN and promiscuous mode on. The appliance's second
     adapter joins it, and the switch then copies it every frame on that VLAN. Nothing else may join
     it: a VM there sees all the LAN's traffic (the panel limits each capture to its machines');
  2. creates the folder Labs/Capture for the appliance;
  3. prints the lines for lab-deploy.env and the build command.

Safe to re-run: an existing port group is brought back to these settings. A distributed switch isn't
handled: make the port group by hand there (docs/admin-guide.md says how).

Unattended:

    setup_capture.py --host vcenter.lab.example --insecure --admin-password-file ~/keys/vcenter-admin \\
        --datacenter Datacenter --cluster Cluster --network "VM Network" --yes
"""

import argparse
import getpass
import sys
from pathlib import Path

from setup_vcenter import FOLDER, all_of, ask, child_folder, choose, connect, read_secret, yes

try:
    from pyVim.connect import Disconnect
    from pyVmomi import vim
except ImportError:
    sys.exit("pyVmomi isn't installed. Install it with:  pip install pyvmomi")

PORT_GROUP = "LAN-capture"
CAPTURE_FOLDER = "Capture"
APPLIANCE = "lab-capture"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--host", help="vCenter address (IP or hostname)")
    p.add_argument("--insecure", action="store_true", default=None, help="accept vCenter's self-signed certificate")
    p.add_argument("--admin", help="administrator account (default: administrator@vsphere.local)")
    p.add_argument("--admin-password-file", help="file with the administrator's password (or user, then password)")
    p.add_argument("--datacenter")
    p.add_argument("--cluster", help="cluster, or standalone host")
    p.add_argument("--network", help="the LAN port group")
    p.add_argument("--port-group", default=PORT_GROUP, help=f"the capture port group's name (default {PORT_GROUP})")
    p.add_argument("--yes", action="store_true", help="don't ask before changing anything")
    return p.parse_args(argv)


def capture_spec(name, lan):
    """The capture port group: the LAN's VLAN and vSwitch, promiscuous. It never sends, so forged
    transmits and MAC changes stay refused."""
    security = vim.host.NetworkPolicy.SecurityPolicy(allowPromiscuous=True, macChanges=False, forgedTransmits=False)
    return vim.host.PortGroup.Specification(
        name=name, vlanId=lan.spec.vlanId, vswitchName=lan.spec.vswitchName, policy=vim.host.NetworkPolicy(security=security)
    )


def main(args):
    print("Prepares vCenter for packet captures. Nothing changes until you confirm.\n")
    host = args.host or ask("vCenter address (IP or hostname)")
    insecure = args.insecure if args.insecure is not None else yes("Accept vCenter's self-signed certificate?", True)
    file_user, password = read_secret(Path(args.admin_password_file)) if args.admin_password_file else (None, None)
    admin = args.admin or file_user or ask("Administrator account", "administrator@vsphere.local")
    if password is None:
        password = getpass.getpass(f"Password for {admin}: ")

    si = connect(host, admin, password, insecure)
    try:
        content = si.RetrieveContent()
        datacenters = [e for e in content.rootFolder.childEntity if isinstance(e, vim.Datacenter)]
        dc = choose("datacenter", datacenters, wanted=args.datacenter)
        compute = choose("cluster or host", all_of(content, vim.ComputeResource, dc.hostFolder), wanted=args.cluster)
        network = choose("LAN port group", sorted(compute.network, key=lambda n: n.name), wanted=args.network)
        if isinstance(network, vim.dvs.DistributedVirtualPortgroup):
            sys.exit(
                f"{network.name} is on a distributed switch, which this script doesn't handle. Add a distributed "
                f"port group named {args.port_group} by hand, with {network.name}'s VLAN and Security → Promiscuous "
                "mode set to Accept (docs/admin-guide.md, \"Packet capture\")."
            )

        plan = []
        for h in compute.host:
            lan = next((pg for pg in h.config.network.portgroup if pg.spec.name == network.name), None)
            if lan is None:
                print(f"  {h.name}: has no {network.name}; skipped")
                continue
            existing = next((pg for pg in h.config.network.portgroup if pg.spec.name == args.port_group), None)
            plan.append((h, lan, existing))
            what = "update" if existing else "add"
            print(f"  {h.name}: {what} {args.port_group} on {lan.spec.vswitchName}, VLAN {lan.spec.vlanId}, promiscuous")
        if not plan:
            sys.exit(f"No host has {network.name}.")
        print(f"  folder {FOLDER}/{CAPTURE_FOLDER}, for the appliance")
        if not args.yes and not yes("\nGo ahead?", True):
            sys.exit("Nothing changed.")

        for h, lan, existing in plan:
            spec = capture_spec(args.port_group, lan)
            ns = h.configManager.networkSystem
            if existing:
                ns.UpdatePortGroup(pgName=args.port_group, portgrp=spec)
            else:
                ns.AddPortGroup(portgrp=spec)
            print(f"{h.name}: {args.port_group} {'updated' if existing else 'added'}")
        labs, _ = child_folder(dc.vmFolder, FOLDER)
        _, made = child_folder(labs, CAPTURE_FOLDER)
        print(f"Folder {FOLDER}/{CAPTURE_FOLDER}: {'created' if made else 'already there'}")

        print(
            "\nNext:\n"
            "  1. Copy the panel's public key from its Admin page (Packet capture), then build the appliance:\n"
            f'       packer/build.sh capture -var panel_key="ssh-ed25519 AAAA… lab-deploy-capture" -var capture_network={args.port_group}\n'
            f"  2. Power on {APPLIANCE} (in {FOLDER}/{CAPTURE_FOLDER}), and add to /srv/lab-deploy/lab-deploy.env:\n"
            f"       CAPTURE_VM={FOLDER}/{CAPTURE_FOLDER}/{APPLIANCE}\n"
            "  3. Restart the API: docker compose up -d api"
        )
    finally:
        Disconnect(si)


if __name__ == "__main__":
    main(parse_args())
