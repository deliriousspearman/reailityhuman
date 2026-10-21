# Proxmox VE 7 template for the panel (docs/build-templates.md):
#
#   packer/build.sh proxmox7
#
# Proxmox VE 7's installer can't run unattended (its automated installer came with 8.2), so this
# installs Debian 11 the way packer/debian does (its preseed), then Proxmox VE 7 on top from Proxmox's
# repository, as Proxmox documents ("Install Proxmox VE on Debian 11 Bullseye"). Then the same
# scripts as packer/proxmox: scripts/template/proxmox/prepare-proxmox.sh (the vmbr0 bridge on DHCP,
# lab-firstboot) and clean-proxmox.sh. Nested virtualisation is on.

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
# Debian's archive, as host and directory; a LAN mirror of it when offline.
# Offline: a LAN mirror of download.proxmox.com/debian (install-pve7.sh).
variable "proxmox_mirror" {
  type    = string
  default = ""
}
variable "debian_mirror_host" {
  type    = string
  default = "deb.debian.org"
}
variable "debian_mirror_dir" {
  type    = string
  default = "/debian"
}

variable "iso" {
  type    = string
  default = "debian-11.11.0-amd64-netinst.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
variable "http_ip" {
  type    = string
  default = ""
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-proxmox-7.4-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "proxmox7" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Proxmox VE 7 template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "debian11_64Guest"
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

  iso_paths    = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  remove_cdrom = true

  http_ip = var.http_ip != "" ? var.http_ip : null
  http_content = {
    "/preseed.cfg" = templatefile("${path.root}/../debian/preseed.pkrtpl.cfg", {
      mirror_host    = var.debian_mirror_host
      mirror_dir     = var.debian_mirror_dir
      codename       = "bullseye"
      password_hash  = bcrypt(uuidv4())
      ssh_public_key = var.ssh_public_key
      # 11's security packages are gone from security.debian.org (see packer/debian).
      services              = "updates"
      allow_unauthenticated = false
    })
  }

  boot_wait = "5s"
  boot_command = [
    "c<wait2>",
    "linux /install.amd/vmlinuz auto=true priority=critical url=http://{{ .HTTPIP }}:{{ .HTTPPort }}/preseed.cfg hostname=pve-template domain=lab.example --- quiet<enter><wait2>",
    "initrd /install.amd/initrd.gz<enter><wait2>",
    "boot<enter>",
  ]

  ip_wait_timeout      = "120m"
  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "120m"

  shutdown_command    = "sudo bash /tmp/proxmox/clean-proxmox.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.proxmox7"]

  provisioner "file" {
    sources     = ["${path.root}/install-pve7.sh", "${path.root}/proxmox-release-bullseye.gpg", "${path.root}/../../scripts/template/proxmox"]
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo LAB_PROXMOX_MIRROR=${var.proxmox_mirror} bash /tmp/install-pve7.sh", "sudo bash /tmp/proxmox/prepare-proxmox.sh"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/proxmox-7.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
