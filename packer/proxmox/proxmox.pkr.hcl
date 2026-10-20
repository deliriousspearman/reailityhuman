# Proxmox VE template for the panel, built unattended (docs/build-templates.md):
#
#   packer/proxmox/prepare-iso.sh     # once per release: the unattended installer ISO
#   packer/build.sh proxmox
#   packer/proxmox/prepare-iso.sh proxmox-ve-8.4
#   packer/build.sh proxmox -var version=8.4 -var iso=proxmox-ve_8.4-1-auto.iso
#
# A hypervisor inside a VM: nested virtualisation is on, so machines in it can run with KVM. The
# installer runs on its own (Proxmox's automated installation), reading answer.pkrtpl.toml from a
# CD; the ISO's first-boot script adds VMware Tools, and Packer then signs in as root with its key.
# Proxmox has cloud-init only for its guests, so it gets the panel's data the way legacy Linux does
# (templates.yaml: family legacy): scripts/template/proxmox/lab-firstboot, which also renames the
# node and keeps /etc/hosts pointing at the machine's own address, as Proxmox needs.

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
  default = "9.2"
}
# The ISO prepare-iso.sh made.
variable "iso" {
  type    = string
  default = "proxmox-ve_9.2-1-auto.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-proxmox-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  # Proxmox VE 8's answer file names its keys differently (root_password, disk_list...).
  answer = startswith(var.version, "8.") ? "answer8.pkrtpl.toml" : "answer.pkrtpl.toml"
}

source "vsphere-iso" "proxmox" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Proxmox VE ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "debian12_64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 4096
  NestedHV             = true
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 65536
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  cd_label  = "PROXMOX-AIS"
  cd_content = {
    "answer.toml" = templatefile("${path.root}/${local.answer}", {
      root_password = var.build_password
      ssh_key       = var.ssh_public_key
    })
  }
  remove_cdrom = true

  # The empty disk falls through to the CD, whose boot menu starts the automated installation by
  # itself; after the install the system boots from disk.
  boot_order = "disk,cdrom"
  boot_wait  = "5s"

  ip_wait_timeout      = "45m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "45m"

  shutdown_command    = "bash /tmp/proxmox/clean-proxmox.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.proxmox"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/proxmox"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["bash /tmp/proxmox/prepare-proxmox.sh"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/proxmox-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
