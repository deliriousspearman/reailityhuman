# Alpine Linux template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh alpine
#
# Boots Alpine's virt ISO, signs in to the live system as root, and runs setup-alpine with the answer
# file on the build CD (answers.pkrtpl: a system install on the whole disk, OpenSSH, and the build's
# SSH key for root). The build reboots into it, runs scripts/template/alpine/prepare-alpine.sh (VMware
# Tools, sudo, and the legacy family's lab-firstboot, which sets up each clone's user from the panel's
# guestinfo), then clean-alpine.sh as the shutdown, leaving a template in Labs/Templates with its
# "clean" snapshot. Alpine has no extras: it's a small, plain server.
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
  default = "3.24"
}
variable "iso" {
  type    = string
  default = "alpine-virt-3.24.3-x86_64.iso"
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
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-alpine-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "alpine" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Alpine Linux ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "other5xLinux64Guest"
  firmware             = "efi"
  CPUs                 = 1
  RAM                  = 1024
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 8192
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  cd_label  = "LABBUILD"
  cd_content = {
    "answers" = templatefile("${path.root}/answers.pkrtpl", { ssh_public_key = var.ssh_public_key })
  }
  remove_cdrom = true

  # The live system's login prompt, then setup-alpine from the build CD, with root's password empty
  # (-e: root signs in with the build key only) and the disk left out. VMware Tools go into the live
  # system next, so it reports its address to Packer; setup-disk then installs it all on the disk,
  # Tools included (it takes the live system's packages and settings), without asking (ERASE_DISKS).
  boot_wait = "30s"
  boot_command = [
    "root<enter><wait3>",
    "mkdir -p /media/lab && mount -t iso9660 $(findfs LABEL=LABBUILD) /media/lab<enter><wait2>",
    "setup-alpine -e -f /media/lab/answers && apk add -q open-vm-tools open-vm-tools-guestinfo && rc-update add open-vm-tools default && rc-service open-vm-tools start && ",
    "ERASE_DISKS=/dev/sda setup-disk -m sys /dev/sda && umount /media/lab && reboot<enter>",
  ]

  ip_wait_timeout      = "30m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "30m"

  shutdown_command    = "sh /tmp/alpine/clean-alpine.sh --yes"
  shutdown_timeout    = "10m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.alpine"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/alpine", "${path.root}/../../scripts/template/legacy/lab-firstboot"]
    destination = "/tmp/"
  }
  provisioner "shell" {
    inline          = ["mv /tmp/lab-firstboot /tmp/alpine/ && sh /tmp/alpine/prepare-alpine.sh"]
    execute_command = "chmod +x {{ .Path }}; env {{ .Vars }} sh {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/alpine-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
