# pfSense CE firewall template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh pfsense
#
# 2.7.2: the last release with an offline installer. pfSense has no cloud-init, so it gets the panel's
# data the way OPNsense does (templates.yaml: family legacy): scripts/template/pfsense/lab-firstboot
# reads the guestinfo.lab.* keys through VMware Tools at the end of each new machine's first boot,
# and sets the hostname and admin's password and key with pfSense's own functions.
#
# The installer is a text menu, so boot_command types the answers (defaults throughout: ZFS, the one
# disk), then picks its Shell, where live.sh puts config.pkrtpl.xml on the new disk and reboots. The
# installer itself never brings up the network. The installed system's first boot installs VMware
# Tools (a one-time command in that configuration), so Packer finds its address and signs in as
# admin with its SSH key.

packer {
  required_plugins {
    vsphere = {
      source  = "github.com/hashicorp/vsphere"
      version = "~> 2.5"
    }
  }
}

variable "vcenter_server" { type = string }
variable "vcenter_username" {
  type      = string
  sensitive = true
}
variable "vcenter_password" {
  type      = string
  sensitive = true
}
variable "vcenter_insecure" {
  type    = bool
  default = false
}
variable "datacenter" { type = string }
variable "cluster" { type = string }
variable "datastore" { type = string }
variable "network" { type = string }
variable "template_folder" {
  type    = string
  default = "Labs/Templates"
}
variable "iso_folder" {
  type    = string
  default = "ISO"
}
variable "apt_mirror" {
  type    = string
  default = ""
}

# Offline: the media folder's address (scripts/isos/fetch-media.sh); VMware Tools are installed from its
# freebsd/pfsense-<version> folder instead of the vendor's package repository.
variable "media_url" {
  type    = string
  default = ""
}
variable "version" {
  type    = string
  default = "2.7.2"
}
variable "iso" {
  type    = string
  default = "pfSense-CE-2.7.2-RELEASE-amd64.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
# admin's password while building (build.sh makes a random one); Packer signs in with the key.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-pfsense-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  # The first boot's VMware Tools (config.pkrtpl.xml): from pfSense's repository, or offline from the
  # media folder (its install.sh, from fetch-pkgs.py, with the dependencies).
  pkg_url        = var.media_url == "" ? "" : "${trimsuffix(var.media_url, "/")}/freebsd/pfsense-${var.version}"
  vmware_install = local.pkg_url == "" ? "pkg-static install -y pfSense-pkg-Open-VM-Tools" : "fetch -qo /tmp/lab-install.sh ${local.pkg_url}/install.sh &amp;&amp; sh /tmp/lab-install.sh ${local.pkg_url}"
}

source "vsphere-iso" "pfsense" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "pfSense CE ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "freebsd14_64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 2048
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 16384
    disk_thin_provisioned = true
  }
  # WAN (vmx0) and LAN (vmx1): both on the lab network for now.
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  cd_label  = "LABBUILD"
  cd_files  = ["${path.root}/live.sh"]
  cd_content = {
    "config.xml" = templatefile("${path.root}/config.pkrtpl.xml", {
      admin_hash      = bcrypt(var.build_password)
      authorized_keys = base64encode(var.ssh_public_key)
      vmware_install  = local.vmware_install
    })
  }
  remove_cdrom = true

  # The empty disk falls through to the CD. The installer's answers, in order: Accept the notice;
  # Install; Auto (ZFS); Install (its settings as they are); stripe; the disk, da0 (Space ticks it);
  # Yes to wiping it; then, once installed, Shell rather than Reboot, where live.sh does the rest.
  boot_order = "disk,cdrom"
  boot_wait  = "5s"
  boot_command = [
    "<wait90>",
    "<enter><wait5>",
    "<enter><wait5>",
    "<enter><wait5>",
    "<enter><wait5>",
    "<enter><wait5>",
    "<spacebar><wait1><enter><wait5>",
    "<left><wait1><enter>",
    "<wait300>",
    "<right><wait1><enter><wait5>",
    "mkdir -p /tmp/lab && mount_cd9660 /dev/iso9660/LABBUILD /tmp/lab && sh /tmp/lab/live.sh<enter>",
  ]

  ip_wait_timeout      = "45m"
  communicator         = "ssh"
  ssh_username         = "admin"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "45m"

  shutdown_command    = "sh /tmp/pfsense/clean-pfsense.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.pfsense"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/pfsense"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline           = ["sh /tmp/pfsense/prepare-pfsense.sh"]
    environment_vars = local.pkg_url == "" ? [] : ["LAB_PKG_URL=${local.pkg_url}"]
    # admin's shell is pfSense's console menu, which runs what it's given with -c through /bin/sh.
    execute_command = "chmod +x {{ .Path }}; env {{ .Vars }} {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/pfsense-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
