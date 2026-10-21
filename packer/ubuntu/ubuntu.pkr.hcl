# Ubuntu Server template for the panel, built unattended (docs/build-templates.md).
#
#   packer/build.sh ubuntu
#
# Installs from the ISO on the datastore with autoinstall (user-data.pkrtpl.hcl, on a small CD),
# runs scripts/template/prepare.sh, then clean.sh as the shutdown, and leaves a template in
# Labs/Templates with its "clean" snapshot: the same steps as docs/setup-vsphere.md part 2, by hand.

packer {
  required_plugins {
    vsphere = {
      source  = "github.com/hashicorp/vsphere"
      version = "~> 2.5"
    }
  }
}

# vCenter and where things go: packer/lab.pkrvars.hcl (see lab.pkrvars.hcl.example), and the
# account from the environment (build.sh sets PKR_VAR_vcenter_username and _password).
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
# Optional: an apt mirror for the install and prepare.sh, e.g. http://mirror.lab.example/ubuntu.
# Empty: Ubuntu's own archive (needs the internet).
variable "apt_mirror" {
  type    = string
  default = ""
}

# This build
variable "version" {
  type    = string
  default = "26.04"
}
# The ISO's name in the datastore's ISO folder (scripts/isos/isos.txt, "ubuntu-26.04").
variable "iso" {
  type    = string
  default = "ubuntu-26.04.1-live-server-amd64.iso"
}
# --extras= for prepare.sh: "" bakes in every extra for Debian-family templates; "none" none.
# Offline: where the media folder from scripts/isos/fetch-media.sh is served on the LAN (its linux/
# part), e.g. http://mirror.lab.example/lab-media. prepare.sh then downloads WordPress, WP-CLI,
# Nextcloud, Chinook, the container images, MinIO, the Pythons and iRedMail from there. Empty: from
# their own sites (MinIO: built from source). (The Nextcloud snap needs the Snap
# Store: leave it out of offline builds with -var extras=… .)
# The Zimbra template instead (scripts/template/zimbra): Ubuntu 20.04 with Zimbra 8.8.15 installed, and
# no other extras. Offline, zimbra_mirror is a mirror of https://repo.zimbra.com, for its packages.
variable "zimbra" {
  type    = bool
  default = false
}
variable "zimbra_mirror" {
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
# The template's name in vCenter; default tpl-ubuntu-<version>-<date>. backend/templates.yaml's
# vsphere: must name it.
variable "vm_name" {
  type    = string
  default = ""
}
# The temporary build user's key (build.sh makes a throwaway pair for each build).
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }

locals {
  name        = var.zimbra ? "zimbra-8.8.15" : "ubuntu-${var.version}"
  vm_name     = var.vm_name != "" ? var.vm_name : "tpl-${local.name}-${formatdate("YYYYMMDD", timestamp())}"
  extras_flag = var.zimbra ? "--extras=zimbra" : (var.extras == "" ? "" : (var.extras == "none" ? "--no-extras" : "--extras=${var.extras}"))
  media       = trimsuffix(var.media_url, "/")
  # prepare.sh reads these from its environment (sudo would drop Packer's, hence env).
  media_env = local.media == "" ? "" : join(" ", [
    "WORDPRESS_URL=${local.media}/linux/wordpress/latest.tar.gz",
    "WP_CLI_URL=${local.media}/linux/wp-cli/wp-cli.phar",
    "NEXTCLOUD_URL=${local.media}/linux/nextcloud/latest.tar.bz2",
    "CHINOOK_URL=${local.media}/linux/chinook",
    "DOCKER_IMAGES_FROM=${local.media}/linux/docker",
    "MINIO_FROM=${local.media}/linux/minio",
    "PYTHON_FROM=${local.media}/linux/python",
    "IREDMAIL_FROM=${local.media}/linux/iredmail",
    "ZIMBRA_URL=${local.media}/linux/zimbra",
  ])
  zimbra_env = var.zimbra_mirror == "" ? "" : "ZIMBRA_MIRROR=${trimsuffix(var.zimbra_mirror, "/")}"
}

source "vsphere-iso" "ubuntu" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "${var.zimbra ? "Zimbra 8.8.15 on Ubuntu 20.04" : "Ubuntu ${var.version}"} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "ubuntu64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = var.zimbra ? 4096 : 2048
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = var.zimbra ? 40960 : 25600
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  # autoinstall's answers, found by the installer through the CD's "cidata" label.
  cd_label = "cidata"
  cd_content = {
    "meta-data" = ""
    "user-data" = templatefile("${path.root}/user-data.pkrtpl.hcl", {
      ssh_public_key = var.ssh_public_key
      apt_mirror     = var.apt_mirror
      # Older installers (20.04's) don't know the option; prepare.sh grows the root volume anyway.
      sizing_all = !contains(["18", "20"], split(".", var.version)[0])
    })
  }
  remove_cdrom = true

  # GRUB's command line: boot the installer with "autoinstall", so it doesn't ask before wiping the disk.
  boot_wait = "5s"
  boot_command = [
    "c<wait2>",
    "linux /casper/vmlinuz autoinstall ---<enter><wait2>",
    "initrd /casper/initrd<enter><wait2>",
    "boot<enter>",
  ]

  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "60m"

  # clean.sh deletes the build user and powers off; then the snapshot and the template.
  shutdown_command    = "sudo bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.ubuntu"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/build-minio.sh", "${path.root}/../../scripts/template/clean.sh", "${path.root}/../../scripts/template/zimbra"]
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo env ${local.media_env} ${local.zimbra_env} bash /tmp/prepare.sh ${local.extras_flag}"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/${local.name}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = var.extras
    }
  }
}
