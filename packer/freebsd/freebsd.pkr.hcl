# FreeBSD template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh freebsd
#
# Boots FreeBSD's disc1 ISO into its installer's shell, and runs bsdinstall with the script on the build
# CD (installerconfig.pkrtpl: UFS on the whole disk, sshd, DHCP, VMware Tools, and the build's SSH key
# for root). The build reboots into it, runs scripts/template/freebsd/prepare-freebsd.sh (updates, sudo,
# and lab-firstboot, which sets up each clone's user from the panel's guestinfo, as on the legacy
# templates), then clean-freebsd.sh as the shutdown, leaving a template in Labs/Templates with its
# "clean" snapshot. No extras: a plain FreeBSD server.
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
  default = "15.1"
}
variable "iso" {
  type    = string
  default = "FreeBSD-15.1-RELEASE-amd64-disc1.iso"
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

# Offline: the installer's media folder, served over HTTP (scripts/isos/fetch-media.sh): the release's
# sets and the packages come from there, and FreeBSD's online updates are skipped.
variable "media_url" {
  type    = string
  default = ""
}

locals {
  vm_name   = var.vm_name != "" ? var.vm_name : "tpl-freebsd-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  offline   = var.media_url != ""
  media     = trimsuffix(var.media_url, "/")
  dist_site = local.offline ? "${local.media}/freebsd/${var.version}-RELEASE" : "https://download.freebsd.org/releases/amd64/${var.version}-RELEASE"
  pkg_url   = local.offline ? "${local.media}/freebsd/freebsd-${var.version}" : ""
}

source "vsphere-iso" "freebsd" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "FreeBSD ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "freebsd14_64Guest"
  firmware             = "efi"
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
  cd_label  = "LABBUILD"
  cd_content = {
    "installerconfig" = templatefile("${path.root}/installerconfig.pkrtpl", { ssh_public_key = var.ssh_public_key, dist_site = local.dist_site, pkg_url = local.pkg_url })
  }
  remove_cdrom = true

  # The installer's welcome: Shell. There, an address by DHCP. The installer's /etc/resolv.conf is a link
  # to /tmp/bsdinstall_etc/resolv.conf, so that folder first, or there's no DNS; and a copy of it, as
  # bsdinstall empties the folder when it starts (installerconfig puts it back, for the downloads and
  # the new system). Then bsdinstall's scripted install from the build CD, and a reboot into it.
  boot_wait = "60s"
  boot_command = [
    "<right><enter><wait5>",
    "mkdir -p /tmp/lab /tmp/bsdinstall_etc && dhclient vmx0 && cp /etc/resolv.conf /tmp/lab-resolv.conf && ",
    "mount_cd9660 /dev/iso9660/LABBUILD /tmp/lab && bsdinstall script /tmp/lab/installerconfig && reboot<enter>",
  ]

  ip_wait_timeout      = "30m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "30m"

  shutdown_command    = "sh /tmp/freebsd/clean-freebsd.sh --yes"
  shutdown_timeout    = "10m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.freebsd"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/freebsd"
    destination = "/tmp/"
  }
  provisioner "shell" {
    inline           = ["sh /tmp/freebsd/prepare-freebsd.sh"]
    environment_vars = local.offline ? ["LAB_OFFLINE=1"] : []
    execute_command  = "chmod +x {{ .Path }}; env {{ .Vars }} sh {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/freebsd-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
