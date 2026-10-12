# Setting up vSphere for the panel

What to do once, by hand, before the panel can deploy machines:

1. Prepare vCenter: folders and a service account.
2. Build the Ubuntu 22.04 template.
3. Give the panel the vCenter details.
4. Deploy a test machine.

Names below (`ProLabs/Templates`, `tpl-ubuntu-22.04`…) are the defaults the panel expects. If you use
others, change them in `lab-deploy.env` and `backend/templates.yaml` to match.

## 1. vCenter

### Folders

In **VMs and Templates**, under your datacenter, create a folder `ProLabs` with two folders inside it:

- `ProLabs/Templates`: the templates machines are cloned from.
- `ProLabs/Machines`: where the panel puts machines. Leave other VMs out of it. The panel looks
  machines up by name here, and its capacity figures count everything on the cluster.

Optionally, create a resource pool (e.g. `ProLabs`) in the cluster to cap what machines can use, and
set `VCENTER_RESOURCE_POOL` to its name.

### Service account

The panel signs in to vCenter as its own account, so what it can do is limited and easy to audit.
Using `administrator@vsphere.local` works for a first test, but switch to this account before
anyone else uses the panel.

1. **Create the user.** In **Administration → Single Sign On → Users and Groups**, create
   `svc-labdeploy` in `vsphere.local`.
2. **Create a role.** In **Administration → Access Control → Roles**, create a role
   `Lab Deploy` with these privileges:

   | Category | Privileges |
   |---|---|
   | Datastore | Allocate space; Browse datastore |
   | Network | Assign network |
   | Resource | Assign virtual machine to resource pool |
   | Virtual machine → Change Configuration | Advanced configuration; Change CPU count; Change Memory; Change Settings; Modify device settings |
   | Virtual machine → Edit Inventory | Create from existing; Remove |
   | Virtual machine → Interaction | Power off; Power on; Reset |
   | Virtual machine → Provisioning | Clone template; Clone virtual machine; Deploy template |
   | Virtual machine → Snapshot management | Create snapshot; Revert to snapshot |

3. **Grant the role.** Give `svc-labdeploy` the `Lab Deploy` role, with **Propagate to children**
   ticked, on each of these:
   - the `ProLabs` folder;
   - the cluster (or the `ProLabs` resource pool);
   - the datastore machines go on;
   - the LAN port group machines join (on a distributed switch, grant it on the port group itself).

   Grant **Read-only** on the datacenter, without propagating, so the panel can find its way to
   these objects.

## 2. The Ubuntu 22.04 template

Machines are **linked clones** of the template's snapshot named `clean`:
- each deploy takes seconds, and only the changes use disk space;
- on each machine's first boot, **cloud-init** sets its hostname, creates the `ubuntu` user with a
  generated password (plus your SSH key, if you gave one), and turns on DHCP.

The template therefore needs cloud-init and VMware Tools, with all trace of its own first boot removed.

### Create the VM

1. **Upload the ISO.** Put `ubuntu-22.04.x-live-server-amd64.iso` on a datastore.
2. **Create the VM** in `ProLabs/Templates`, named `tpl-ubuntu-22.04`:
   - Guest OS: Linux, Ubuntu Linux (64-bit)
   - 2 vCPU, 2 GB memory, 20 GB disk, **thin provisioned**
   - Network adapter: **VMXNET3**, on the LAN port group
   - CD/DVD: the ISO, **Connect at power on**
3. **Install Ubuntu Server**:
   - accept the defaults;
   - tick **Install OpenSSH server**;
   - create any user, e.g. `builder`. It's deleted at the end.
4. **Reboot**, disconnect the CD/DVD, and SSH in as `builder` (the console shows its address).

### Prepare it

Update it, and make sure VMware Tools and cloud-init are installed:

```sh
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y open-vm-tools cloud-init
```

Let cloud-init configure the network and read its data from vCenter. The installer turned both off.

```sh
sudo rm -f /etc/cloud/cloud.cfg.d/99-installer.cfg \
           /etc/cloud/cloud.cfg.d/subiquity-disable-cloudinit-networking.cfg \
           /etc/cloud/cloud.cfg.d/90-installer-network.cfg
echo 'datasource_list: [VMware, NoCloud, None]' | sudo tee /etc/cloud/cloud.cfg.d/99-vmware.cfg
sudo rm -f /etc/netplan/00-installer-config.yaml /etc/netplan/50-cloud-init.yaml
```

Optionally, install anything every machine should have, now.

### Clean it, and shut it down

This forgets the template's own identity so each clone gets its own. It also deletes `builder` and
powers off, so run it as one command. Your SSH session ends.

```sh
sudo sh -c 'cloud-init clean --logs --seed --machine-id
  truncate -s 0 /etc/machine-id; rm -f /var/lib/dbus/machine-id
  rm -f /etc/ssh/ssh_host_*
  userdel -r -f builder
  shutdown -h now'
```

Keep the machine-id step: without it, clones can end up sharing one DHCP lease. (The panel also asks
for leases by MAC address, but don't rely on that alone.)

### Snapshot it, and make it a template

With the VM powered off:

1. **Take a snapshot** named exactly **`clean`**. Leave "Include virtual machine's memory" unticked.
2. **Convert it:** right-click, then **Template → Convert to Template**.

Don't delete the template, or its `clean` snapshot, while any machine exists: every machine's disk is
built on top of that snapshot.

To update it later, build a new template (e.g. `tpl-ubuntu-22.04-v2`) and point `vsphere:` in
`backend/templates.yaml` at it. Machines that already exist keep using the old one; delete the old
template once they're all gone.

## 3. Tell the panel

On the panel's server, edit `/srv/lab-deploy/lab-deploy.env`. The first deploy created it, with a
database password already filled in. Set the `VCENTER_*` lines:

| Setting | What it is | Where to find it in vCenter |
|---|---|---|
| `VCENTER_HOST` | vCenter's address | The address you open in the browser |
| `VCENTER_USER`, `VCENTER_PASSWORD` | The service account | `svc-labdeploy@vsphere.local` and its password |
| `VCENTER_INSECURE` | `1` to accept vCenter's own self-signed certificate | — |
| `VCENTER_DATACENTER` | Datacenter name | Top level of the inventory |
| `VCENTER_CLUSTER` | Cluster name; or, for a host not in a cluster, the host's name as vCenter shows it | — |
| `VCENTER_DATASTORE` | Datastore name | — |
| `VCENTER_NETWORK` | The LAN port group | e.g. `VM Network` |

Then apply it, on the server:

```sh
cd /srv/lab-deploy && docker compose up -d
curl -sk https://<panel address>/api/health   # {"database":"ok","vcenter":"ok"} once it can sign in
```

Re-running the pipeline does the same.

The server must be able to reach vCenter on port 443. Machines' addresses come from the DHCP server
on the port group; the panel reads them from VMware Tools.

## 4. Check it

1. Open the panel, go to **Machines → Ubuntu Server**, and deploy `ubuntu01` for 2 hours.
2. In vCenter, `ubuntu01-xxxx` appears in `ProLabs/Machines`, as a linked clone, and powers on.
3. Within a minute or two, the panel shows its address. `ssh ubuntu@<address>` works with the
   password on its page, and `hostname` prints `ubuntu01`.
4. Try **Stop**, **Start**, **Reboot**, and **Reset to clean**: a file you created is gone, and
   the password is unchanged.
5. **Destroy** it: the VM is deleted in vCenter.

If something fails, the machine's **Activity** log and **Admin → Jobs** show vCenter's error message.
The worker's own log has the rest: `docker compose -f /srv/lab-deploy/compose.yaml logs worker`.
