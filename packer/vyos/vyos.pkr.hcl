# VyOS router template for the panel, built unattended (docs/build-templates.md):
#
#   packer/vyos/build-iso.sh          # once per VyOS release: the ISO with VMware Tools and cloud-init
#   packer/build.sh vyos
#
# boot_command answers the live system's `install image` (the image is installed with the build's
# password for the vyos user), reboots into it, and switches on SSH and DHCP on both adapters; Packer
# then signs in as vyos. clean-vyos.sh (the shutdown) locks the vyos user, unties the adapters from
# the template's MAC addresses and resets cloud-init. Each machine's own user, password, key and name
# come from the panel through cloud-init (templates.yaml: family vyos).

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
  default = "rolling"
}
# build-iso.sh's output, uploaded to the datastore's ISO folder.
variable "iso" {
  type    = string
  default = "vyos-1.5-rolling-202610180239-vmware-amd64.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
# The vyos user's password while building (build.sh makes a random one); clean-vyos.sh locks it.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-vyos-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "vyos" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "VyOS (${var.version}) template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type = "debian12_64Guest"
  # BIOS: on EFI, the installed disk's fallback loader (shim, then fbx64) reset the VM onto the CD
  # instead of booting the image. A router gains nothing from EFI.
  firmware             = "bios"
  CPUs                 = 2
  RAM                  = 1024
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 10240
    disk_thin_provisioned = true
  }
  # eth0 and eth1: both on the lab network for now.
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths    = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  remove_cdrom = true
  # The empty disk falls through to the CD; after the install, the disk boots.
  boot_order = "disk,cdrom"

  # The live system boots by itself to its login (vyos / vyos). install image's questions, in order:
  # continue, image name, the vyos password twice, console (KVM), disk, wipe it, all of it, which
  # config, after which it copies the image (the long wait). The installed image keeps the live
  # configuration (config 1), vyos's password included, whatever was typed: so it's vyos there too,
  # and the build's password is set after the reboot, with SSH and DHCP on both adapters.
  boot_wait = "60s"
  boot_command = [
    "vyos<enter><wait3>vyos<enter><wait5>",
    "install image<enter><wait5>",
    "y<enter><wait3>",
    "<enter><wait3>",
    "vyos<enter><wait2>vyos<enter><wait3>",
    "<enter><wait3>",
    "<enter><wait5>",
    "y<enter><wait10>",
    "<enter><wait10>",
    "<enter><wait150>",
    "reboot<enter><wait3>y<enter><wait90>",
    "vyos<enter><wait3>vyos<enter><wait5>",
    "configure<enter><wait3>",
    "set system login user vyos authentication plaintext-password ${var.build_password}<enter><wait1>",
    "set service ssh port 22<enter><wait1>",
    "set interfaces ethernet eth0 address dhcp<enter><wait1>",
    "set interfaces ethernet eth1 address dhcp<enter><wait1>",
    "commit<enter><wait10>save<enter><wait3>exit<enter><wait2>",
  ]

  ip_wait_timeout = "30m"
  communicator    = "ssh"
  ssh_username    = "vyos"
  ssh_password    = var.build_password
  ssh_timeout     = "30m"

  shutdown_command    = "vbash /tmp/vyos/clean-vyos.sh --yes"
  shutdown_timeout    = "10m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.vyos"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/vyos"
    destination = "/tmp/"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/vyos-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
