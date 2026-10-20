# TrueNAS CORE template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh truenas-core
#
# The FreeBSD-based TrueNAS, in maintenance mode (SCALE is its successor; 13.3 is the last release).
# Like packer/truenas-scale: two empty data disks besides the boot disk, the panel's data set at first
# boot by scripts/template/truenas/lab-firstboot (a middleware init script; family legacy), and the
# installer's menus answered by boot_command. CORE's administrator is root.

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
  default = "13.3"
}
variable "iso" {
  type    = string
  default = "TrueNAS-13.3-U1.2.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
# root's password while building (build.sh makes a random one).
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-truenas-core-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
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
  notes               = "TrueNAS CORE ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "freebsd13_64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 8192
  disk_controller_type = ["pvscsi"]
  # The boot disk, then two data disks for a pool.
  storage {
    disk_size             = 32768
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
  # first disk (Space ticks it); yes, erase it; root's password twice; boot by UEFI; then, once
  # installed, OK and Reboot. At the installed system's console menu: 9, a shell, where SSH is
  # switched on with root's password allowed.
  boot_order = "disk,cdrom"
  boot_wait  = "5s"
  boot_command = [
    "<wait120>",
    "<enter><wait10>",
    "<spacebar><wait1><enter><wait5>",
    "<enter><wait5>",
    "${var.build_password}<tab>${var.build_password}<enter><wait5>",
    "<enter>",
    "<wait600>",
    "<enter><wait5>",
    "3<enter>",
    "<wait300>",
    "9<enter><wait10>",
    "midclt call ssh.update '{\"rootlogin\": true, \"passwordauth\": true}' >/dev/null && midclt call service.update ssh '{\"enable\": true}' >/dev/null && midclt call service.start ssh && echo SSH-ON<enter>",
  ]

  ip_wait_timeout = "60m"
  communicator    = "ssh"
  ssh_username    = "root"
  ssh_password    = var.build_password
  ssh_timeout     = "60m"

  shutdown_command    = "sh /tmp/truenas/clean-truenas.sh --yes"
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
    inline          = ["sh /tmp/truenas/prepare-truenas.sh"]
    execute_command = "chmod +x {{ .Path }}; env {{ .Vars }} {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/truenas-core-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
