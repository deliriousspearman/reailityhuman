# TrueNAS SCALE template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh truenas-scale
#
# A NAS appliance (Debian underneath, managed through its middleware). It comes with two empty data
# disks besides the boot disk, for a pool. TrueNAS has no cloud-init, so it gets the panel's data the
# way legacy Linux does (templates.yaml: family legacy): scripts/template/truenas/lab-firstboot runs
# at the end of each boot (a middleware init script) and sets the hostname and truenas_admin's
# password and key.
#
# The installer is a text menu, so boot_command types the answers: Install, the first disk, yes,
# truenas_admin with the build's password; then, once installed, Reboot. At the installed system's
# console menu it opens a Linux shell and switches SSH on (off by default), so Packer can sign in.

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
variable "ssh_private_key_file" {
  type    = string
  default = ""
}
variable "ssh_public_key" {
  type    = string
  default = ""
}

variable "version" {
  type    = string
  default = "25.10"
}
variable "iso" {
  type    = string
  default = "TrueNAS-SCALE-25.10.7.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
# truenas_admin's password while building (build.sh makes a random one).
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-truenas-scale-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "truenas" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "TrueNAS SCALE ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "debian12_64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 8192
  disk_controller_type = ["pvscsi"]
  # Three disks the same size: the installer lists them in its own order and takes the first, which
  # becomes the boot disk; the other two are for a pool.
  storage {
    disk_size             = 20480
    disk_thin_provisioned = true
  }
  storage {
    disk_size             = 20480
    disk_thin_provisioned = true
  }
  storage {
    disk_size             = 20480
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths    = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  remove_cdrom = true

  # The empty disk falls through to the CD. The installer's answers, in order: Install/Upgrade; the
  # first disk (Space ticks it); yes, erase it; truenas_admin as the administrator, with its password
  # twice; then, once installed, OK and Reboot. At the installed system's console menu: 8, a Linux
  # shell, where SSH is switched on with passwords allowed, and truenas_admin may use sudo without its
  # password while building (clean-truenas.sh takes that away).
  boot_order = "disk,cdrom"
  boot_wait  = "5s"
  boot_command = [
    "<wait120>",
    "<enter><wait10>",
    "<spacebar><wait1><enter><wait5>",
    "<enter><wait5>",
    "<enter><wait5>",
    "${var.build_password}<tab>${var.build_password}<enter>",
    "<wait600>",
    "<enter><wait5>",
    "3<enter>",
    "<wait300>",
    "8<enter><wait10>",
    "id=$(midclt call user.query '[[\"username\",\"=\",\"truenas_admin\"]]' '{\"get\": true}' | jq .id) && midclt call user.update $id '{\"ssh_password_enabled\": true, \"sudo_commands_nopasswd\": [\"ALL\"]}' >/dev/null && ",
    "midclt call ssh.update '{\"passwordauth\": true}' >/dev/null && midclt call service.update ssh '{\"enable\": true}' >/dev/null && midclt call service.start ssh && clear<enter>",
  ]

  ip_wait_timeout = "60m"
  communicator    = "ssh"
  ssh_username    = "truenas_admin"
  ssh_password    = var.build_password
  ssh_timeout     = "60m"

  shutdown_command    = "sudo bash /tmp/truenas/clean-truenas.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.truenas"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/truenas"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline          = ["bash /tmp/truenas/prepare-truenas.sh"]
    execute_command = "chmod +x {{ .Path }}; sudo env {{ .Vars }} {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/truenas-scale-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
