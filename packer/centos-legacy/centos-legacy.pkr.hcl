# Legacy CentOS templates for the panel (practice targets on old systems), built unattended
# (docs/build-templates.md):
#
#   packer/build.sh centos-legacy                                                          # CentOS 7
#   packer/build.sh centos-legacy -var version=8 -var iso=CentOS-8.5.2111-x86_64-boot.iso
#   packer/build.sh centos-legacy -var version=6 -var iso=CentOS-6.10-x86_64-minimal.iso
#
# Installs from the vault's ISO with a kickstart: 7 and 8 read it from a CD labelled OEMDRV
# (ks.pkrtpl.cfg, ks8.pkrtpl.cfg); 6 fetches it from Packer's web server (ks6.pkrtpl.cfg, so the build
# VM must reach this machine), and gets VMware Tools from EPEL's archive. Packages come from the vault,
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
# The vault's release folder (or a LAN mirror of it). Empty: the version's last release on vault.centos.org.
variable "vault" {
  type    = string
  default = ""
}
# CentOS 6 only: EPEL's archived repository (or a LAN mirror), for VMware Tools.
variable "epel6" {
  type    = string
  default = "http://archives.fedoraproject.org/pub/archive/epel/6/x86_64/"
}
# The address the build VM reaches this machine's web server on (CentOS 6), if Packer guesses wrong.
variable "http_ip" {
  type    = string
  default = ""
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
  release = { "6" = "6.10", "7" = "7.9.2009", "8" = "8.5.2111" }[var.version]
  vault   = trimsuffix(var.vault != "" ? var.vault : "http://vault.centos.org/${local.release}", "/")
  ks = templatefile("${path.root}/ks${var.version == "7" ? "" : var.version}.pkrtpl.cfg", {
    vault          = local.vault
    epel           = var.epel6
    build_password = var.build_password
    ssh_public_key = var.ssh_public_key
  })
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

  guest_os_type        = "centos${var.version}_64Guest"
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
  # 7 and 8: the installer reads ks.cfg from a volume labelled OEMDRV by itself.
  cd_label     = "OEMDRV"
  cd_content   = var.version == "6" ? {} : { "ks.cfg" = local.ks }
  http_content = var.version == "6" ? { "/ks.cfg" = local.ks } : {}
  http_ip      = var.http_ip != "" ? var.http_ip : null
  remove_cdrom = true

  # 7 and 8: the boot menu's default entry checks the media first, so go up to the plain install.
  # 6: the first entry installs; its boot line gets the kickstart's address (Tab edits it).
  boot_wait = "5s"
  boot_command = var.version == "6" ? [
    "<tab><wait> ks=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ks.cfg<enter>",
  ] : ["<up><wait><enter>"]

  ip_wait_timeout = "60m"
  communicator    = "ssh"
  ssh_username    = "builder"
  # CentOS 6's OpenSSH (5.3) predates the build's ed25519 key: it signs in with the build password.
  ssh_private_key_file = var.version == "6" ? null : var.ssh_private_key_file
  ssh_password         = var.version == "6" ? var.build_password : null
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
