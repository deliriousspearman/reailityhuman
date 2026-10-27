# Fedora templates for the panel, Server and Workstation, built unattended
# (docs/build-templates.md):
#
#   packer/build.sh fedora                            # Fedora Server 44
#   packer/build.sh fedora -var edition=workstation   # Fedora Workstation 44
#
# Installs from a netinst ISO with a kickstart (ks.pkrtpl.cfg, on a CD labelled OEMDRV, which the
# installer reads by itself), packages from Fedora's repositories, then runs
# scripts/template/prepare.sh and clean.sh as for the RHEL family, and leaves a template in
# Labs/Templates with its "clean" snapshot. Server comes from Server's netinst; Workstation from the
# Everything netinst with Workstation's package set, as Fedora's Live ISO can't take a kickstart.

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
variable "media_url" {
  type    = string
  default = ""
}
# Offline: a LAN mirror of Fedora, as the folder holding releases/ and updates/ (e.g.
# http://mirror.lab.example/fedora/linux). Empty: Fedora's mirror list.
variable "repo_mirror" {
  type    = string
  default = ""
}

variable "edition" {
  type    = string
  default = "server"
  validation {
    condition     = contains(["server", "workstation"], var.edition)
    error_message = "The edition is server or workstation."
  }
}
variable "version" {
  type    = string
  default = "44"
}
# The netinst ISO's name in the datastore's ISO folder (scripts/isos/isos.txt); default by edition.
variable "iso" {
  type    = string
  default = ""
}
# Default: the RHEL family's extras on Server; on Workstation only its Remote Login (GNOME there has
# no Xorg session for xrdp).
variable "extras" {
  type    = string
  default = ""
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
# The build user's password (build.sh makes a random one); it signs in with its key.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  workstation = var.edition == "workstation"
  isos = {
    "server"      = "Fedora-Server-netinst-x86_64-${var.version}-1.7.iso"
    "workstation" = "Fedora-Everything-netinst-x86_64-${var.version}-1.7.iso"
  }
  mirror      = trimsuffix(var.repo_mirror, "/")
  iso         = var.iso != "" ? var.iso : local.isos[var.edition]
  vm_name     = var.vm_name != "" ? var.vm_name : "tpl-fedora-${var.edition}-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  extras      = var.extras != "" ? var.extras : (local.workstation ? "gnome-remote-login" : "")
  extras_flag = local.extras == "" ? "" : (local.extras == "none" ? "--no-extras" : "--extras=${local.extras}")
}

source "vsphere-iso" "fedora" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Fedora ${var.edition} ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "fedora64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = local.workstation ? 4096 : 2048
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = local.workstation ? 40960 : 20480
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${local.iso}"]
  # The installer reads ks.cfg from a volume labelled OEMDRV by itself.
  cd_label = "OEMDRV"
  cd_content = {
    "ks.cfg" = templatefile("${path.root}/ks.pkrtpl.cfg", {
      edition        = var.edition
      version        = var.version
      mirror         = local.mirror
      build_password = var.build_password
      ssh_public_key = var.ssh_public_key
    })
  }
  remove_cdrom = true

  # GRUB's default entry checks the media first: go up to the plain install.
  boot_wait    = "5s"
  boot_command = ["<up><wait><enter>"]

  ip_wait_timeout      = "60m"
  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "60m"

  shutdown_command    = "sudo bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.fedora"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/clean.sh"]
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo bash /tmp/prepare.sh ${local.extras_flag}"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/fedora-${var.edition}-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = local.extras
    }
  }
}
