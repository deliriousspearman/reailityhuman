# OPNsense firewall template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh opnsense
#
# OPNsense has no cloud-init, so it gets the panel's data the way legacy Linux does (templates.yaml:
# family legacy): scripts/template/opnsense/lab-firstboot reads the guestinfo.lab.* keys through
# VMware Tools and writes them into its config.xml at each new machine's first boot.
#
# The DVD's installer is a text menu, so boot_command types the answers. Before anything else it
# makes the live system's one adapter WAN (a DHCP client) with no LAN: by default the live system
# would make it LAN, with its own address and a DHCP server, on the shared lab network. The live system then
# installs to disk with config.pkrtpl.xml as the configuration and adds VMware Tools (os-vmware), so
# Packer finds the installed system's address and signs in as root with its SSH key.

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

variable "version" {
  type    = string
  default = "26.7"
}
variable "iso" {
  type    = string
  default = "OPNsense-26.7-dvd-amd64.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
# root's password while building (build.sh makes a random one); Packer signs in with the key.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-opnsense-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "opnsense" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "OPNsense ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "freebsd14_64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 2048
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 20480
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
      root_hash       = bcrypt(var.build_password)
      authorized_keys = base64encode(var.ssh_public_key)
    })
  }
  remove_cdrom = true

  # The installer's answers, timed for a 2 GB VM (RAM is part of the answers: under 3 GB the
  # installer warns first). In order: Space pauses the loader menu's short countdown (harmless until
  # the menu is up); 3, the loader prompt, where the adapters are switched off for the live system;
  # root's sign-in (the live password, opnsense); 8, a shell, where live.sh puts the lab configuration
  # in place and starts the installer: default keymap, Install (UFS), past the RAM warning, disk da0,
  # yes; then Complete Install, past its reboot (Esc, Ctrl+C on its 5-second countdown), and
  # live.sh after, which readies the installed disk and reboots into it.
  boot_wait = "1s"
  boot_command = [
    "<spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar><wait1>",
    "<spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar><wait1>",
    "<spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar><wait2>",
    "3<wait3>",
    "set hint.vmx.0.disabled=1<enter>set hint.vmx.1.disabled=1<enter>boot<enter>",
    "<wait150>",
    "root<enter><wait3>opnsense<enter><wait8>8<enter><wait3>",
    "mkdir -p /tmp/lab && mount -t cd9660 /dev/iso9660/LABBUILD /tmp/lab && sh /tmp/lab/live.sh before && opnsense-installer<enter><wait10>",
    "<enter><wait5>",
    "<down><enter><wait5>",
    "<enter><wait5>",
    "d<wait1><enter><wait5>",
    "<enter><wait420>",
    "<down><enter><wait5>",
    "<esc><wait1><leftCtrlOn>c<leftCtrlOff><wait3>",
    "sh /tmp/lab/live.sh after<enter>",
  ]

  ip_wait_timeout      = "60m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "60m"

  shutdown_command    = "sh /tmp/opnsense/clean-opnsense.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.opnsense"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/opnsense"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sh /tmp/opnsense/prepare-opnsense.sh"]
    # root's shell is csh, which doesn't take Packer's usual NAME=value prefix: env does.
    execute_command = "chmod +x {{ .Path }}; env {{ .Vars }} {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/opnsense-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
