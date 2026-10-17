# Legacy CentOS templates for the panel (practice targets on old systems), built unattended
# (docs/build-templates.md):
#
#   packer/build.sh centos-legacy              # CentOS 7
#
# Installs from the vault's Minimal ISO with a kickstart (ks.pkrtpl.cfg, on a CD labelled OEMDRV),
# then runs scripts/template/legacy/prepare-legacy.sh and clean-legacy.sh: these systems' cloud-init
# can't read the panel's data, so they get lab-firstboot instead (templates.yaml: family legacy).

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
# The vault's release folder (or a LAN mirror of it), holding os/ and updates/.
variable "vault" {
  type    = string
  default = "http://vault.centos.org/7.9.2009"
}

variable "version" {
  type    = string
  default = "7"
}
variable "iso" {
  type    = string
  default = "CentOS-7-x86_64-Minimal-2207-02.iso"
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
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-centos-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "centos_legacy" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "CentOS ${var.version} (legacy) template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "centos7_64Guest"
  firmware             = "bios"
  CPUs                 = 2
  RAM                  = 2048
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 20480
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  # The installer reads ks.cfg from a volume labelled OEMDRV by itself.
  cd_label = "OEMDRV"
  cd_content = {
    "ks.cfg" = templatefile("${path.root}/ks.pkrtpl.cfg", {
      vault          = trimsuffix(var.vault, "/")
      build_password = var.build_password
      ssh_public_key = var.ssh_public_key
    })
  }
  remove_cdrom = true

  # The boot menu's default entry checks the media first: go up to the plain install.
  boot_wait    = "5s"
  boot_command = ["<up><wait><enter>"]

  ip_wait_timeout      = "60m"
  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "60m"

  shutdown_command    = "sudo bash /tmp/legacy/clean-legacy.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.centos_legacy"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/legacy"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo bash /tmp/legacy/prepare-legacy.sh"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/centos-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
