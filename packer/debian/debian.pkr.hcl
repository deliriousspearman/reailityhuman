# Debian templates for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh debian                                                       # Debian 13
#   packer/build.sh debian -var version=12 -var iso=debian-12.15.0-amd64-netinst.iso
#
# Installs from Debian's netinst ISO with a preseed file (preseed.pkrtpl.cfg, served by Packer's web
# server: the build VM must reach this machine) as a plain server, runs scripts/template/prepare.sh
# (cloud-init, the extras), then clean.sh as the shutdown, and leaves a template in Labs/Templates
# with its "clean" snapshot.

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
variable "debian_mirror_host" {
  type    = string
  default = "deb.debian.org"
}
variable "debian_mirror_dir" {
  type    = string
  default = "/debian"
}

variable "version" {
  type    = string
  default = "13"
}
variable "iso" {
  type    = string
  default = "debian-13.7.0-amd64-netinst.iso"
}
# Offline: where the media folder from scripts/isos/fetch-media.sh is served on the LAN (its linux/
# part), e.g. http://mirror.lab.example/lab-media. prepare.sh then downloads WordPress, WP-CLI,
# Nextcloud and Chinook from there. Empty: from their own sites. (The Nextcloud snap needs the Snap
# Store: leave it out of offline builds with -var extras=… .)
variable "media_url" {
  type    = string
  default = ""
}
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
# The address the build VM reaches this machine's web server on, if Packer guesses wrong.
variable "http_ip" {
  type    = string
  default = ""
}

locals {
  codename    = { "12" = "bookworm", "13" = "trixie" }[var.version]
  vm_name     = var.vm_name != "" ? var.vm_name : "tpl-debian-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  extras_flag = var.extras == "" ? "" : (var.extras == "none" ? "--no-extras" : "--extras=${var.extras}")
  media       = trimsuffix(var.media_url, "/")
  # prepare.sh reads these from its environment (sudo would drop Packer's, hence env).
  media_env = local.media == "" ? "" : join(" ", [
    "WORDPRESS_URL=${local.media}/linux/wordpress/latest.tar.gz",
    "WP_CLI_URL=${local.media}/linux/wp-cli/wp-cli.phar",
    "NEXTCLOUD_URL=${local.media}/linux/nextcloud/latest.tar.bz2",
    "CHINOOK_URL=${local.media}/linux/chinook",
    "DOCKER_IMAGES_FROM=${local.media}/linux/docker",
  ])
}

source "vsphere-iso" "debian" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Debian ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "debian12_64Guest"
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
      mirror_host    = var.debian_mirror_host
      mirror_dir     = var.debian_mirror_dir
      codename       = local.codename
      password_hash  = bcrypt(uuidv4())
      ssh_public_key = var.ssh_public_key
    })
  }

  # GRUB's command line: the text installer, answering everything from the preseed file.
  boot_wait = "5s"
  boot_command = [
    "c<wait2>",
    "linux /install.amd/vmlinuz auto=true priority=critical url=http://{{ .HTTPIP }}:{{ .HTTPPort }}/preseed.cfg hostname=tpl-debian domain= --- quiet<enter><wait2>",
    "initrd /install.amd/initrd.gz<enter><wait2>",
    "boot<enter>",
  ]

  ip_wait_timeout      = "120m"
  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "120m"

  shutdown_command    = "sudo bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.debian"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/clean.sh"]
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo env ${local.media_env} bash /tmp/prepare.sh ${local.extras_flag}"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/debian-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = var.extras
    }
  }
}
