# Older Ubuntu Server templates for the panel (legacy practice targets), from the debian-installer
# ISO, whose live server can't install unattended (docs/build-templates.md):
#
#   packer/build.sh ubuntu-di                 # Ubuntu 18.04
#   packer/build.sh ubuntu-di -var version=16.04 -var iso=ubuntu-16.04.7-server-amd64.iso -var legacy=true
#
# A preseed file (preseed.pkrtpl.cfg, served by Packer's web server: the build VM must reach this
# machine), then scripts/template/prepare.sh and clean.sh as for the other templates. Newer Ubuntu
# (20.04 on) installs with autoinstall: packer/ubuntu.

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
# Ubuntu's archive, as host and directory; a LAN mirror of it when offline.
variable "ubuntu_mirror_host" {
  type    = string
  default = "archive.ubuntu.com"
}
variable "ubuntu_mirror_dir" {
  type    = string
  default = "/ubuntu"
}

variable "version" {
  type    = string
  default = "18.04"
}
variable "iso" {
  type    = string
  default = "ubuntu-18.04.6-server-amd64.iso"
}
# Offline: where the media folder from scripts/isos/fetch-media.sh is served on the LAN (its linux/
# part), e.g. http://mirror.lab.example/lab-media. prepare.sh then downloads WordPress, WP-CLI,
# Nextcloud, Chinook, MinIO, the Pythons and iRedMail from there. Empty: from
# their own sites (MinIO: built from source). (The Nextcloud snap needs the Snap
# Store: leave it out of offline builds with -var extras=… .)
# Offline: a mirror of https://repo.zabbix.com, for the Zabbix extras' packages.
variable "zabbix_mirror" {
  type    = string
  default = ""
}
variable "media_url" {
  type    = string
  default = ""
}
variable "extras" {
  type    = string
  default = ""
}
# Ubuntu 16.04: its cloud-init can't read the panel's data from vCenter, so it's the legacy family:
# scripts/template/legacy/prepare-legacy.sh and clean-legacy.sh instead of prepare.sh and clean.sh
# (lab-firstboot, no extras).
variable "legacy" {
  type    = bool
  default = false
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
# The build user's password (build.sh makes a random one): 18.04's installer can't take a bcrypt hash.
variable "build_password" {
  type      = string
  sensitive = true
}
# The address the build VM reaches this machine's web server on, if Packer guesses wrong.
variable "http_ip" {
  type    = string
  default = ""
}

locals {
  vm_name     = var.vm_name != "" ? var.vm_name : "tpl-ubuntu-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  extras_flag = var.extras == "" ? "" : (var.extras == "none" ? "--no-extras" : "--extras=${var.extras}")
  media       = trimsuffix(var.media_url, "/")
  # prepare.sh reads these from its environment (sudo would drop Packer's, hence env).
  media_env = local.media == "" ? "" : join(" ", [
    "WORDPRESS_URL=${local.media}/linux/wordpress/latest.tar.gz",
    "WP_CLI_URL=${local.media}/linux/wp-cli/wp-cli.phar",
    "NEXTCLOUD_URL=${local.media}/linux/nextcloud/latest.tar.bz2",
    "CHINOOK_URL=${local.media}/linux/chinook",
    "MINIO_FROM=${local.media}/linux/minio",
    "PYTHON_FROM=${local.media}/linux/python",
    "IREDMAIL_FROM=${local.media}/linux/iredmail",
    "WAZUH_FROM=${local.media}/linux/wazuh",
  ])
  zabbix_env = var.zabbix_mirror == "" ? "" : "ZABBIX_MIRROR=${trimsuffix(var.zabbix_mirror, "/")}"
}

source "vsphere-iso" "ubuntu_di" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Ubuntu ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "ubuntu64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 2048
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 25600
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
    "/preseed.cfg" = templatefile("${path.root}/preseed.pkrtpl.cfg", {
      mirror_host    = var.ubuntu_mirror_host
      mirror_dir     = var.ubuntu_mirror_dir
      build_password = var.build_password
      ssh_public_key = var.ssh_public_key
    })
  }

  # GRUB's command line: the text installer, answering everything from the preseed file.
  boot_wait = "5s"
  boot_command = [
    "c<wait2>",
    "linux /install/vmlinuz auto=true priority=critical url=http://{{ .HTTPIP }}:{{ .HTTPPort }}/preseed.cfg debian-installer/locale=en_US.UTF-8 keyboard-configuration/layoutcode=us hostname=tpl-ubuntu domain= --- quiet<enter><wait2>",
    "initrd /install/initrd.gz<enter><wait2>",
    "boot<enter>",
  ]

  ip_wait_timeout      = "120m"
  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "120m"

  shutdown_command    = var.legacy ? "sudo bash /tmp/legacy/clean-legacy.sh --yes" : "sudo bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.ubuntu_di"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/build-minio.sh", "${path.root}/../../scripts/template/clean.sh"]
    destination = "/tmp/"
  }

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/legacy"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = [var.legacy ? "sudo bash /tmp/legacy/prepare-legacy.sh" : "sudo env ${local.media_env} ${local.zabbix_env} bash /tmp/prepare.sh ${local.extras_flag}"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/ubuntu-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = var.extras
    }
  }
}
