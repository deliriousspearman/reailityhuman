# Parrot Security template for the panel (docs/build-templates.md):
#
#   packer/parrot/import-base.sh <Parrot-security-*.ova>     # once per Parrot release
#   packer/build.sh parrot
#
# Parrot's installer can't be answered unattended, so this starts from Parrot's own VM image (the
# Security OVA), imported once as the VM parrot-base-<version> with SSH switched on (import-base.sh).
# Packer clones it, signs in as the image's own user, runs scripts/template/prepare.sh, then clean.sh
# as the shutdown (which deletes that user, its well-known password and its automatic sign-in), and
# leaves a template in Labs/Templates with its "clean" snapshot.

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
# build.sh's throwaway key: not used here (the image's own user signs in with its password).
variable "ssh_private_key_file" {
  type    = string
  default = ""
}
variable "ssh_public_key" {
  type    = string
  default = ""
}
# Offline: as for Ubuntu (ubuntu.pkr.hcl). Parrot's packages also need its repository: point
# /etc/apt/sources.list.d/parrot.list at a LAN mirror in the base VM.
variable "media_url" {
  type    = string
  default = ""
}

variable "version" {
  type    = string
  default = "7.4"
}
# The imported image (import-base.sh), in the template folder.
variable "base_vm" {
  type    = string
  default = "parrot-base-7.4"
}
# The image's own user and its published password: deleted from the template by clean.sh.
variable "image_user" {
  type    = string
  default = "user"
}
# Not marked sensitive: it's the image's published default, and Packer would mask every "parrot" in
# its output.
variable "image_password" {
  type    = string
  default = "parrot"
}
variable "extras" {
  type    = string
  default = ""
}
variable "vm_name" {
  type    = string
  default = ""
}

locals {
  vm_name     = var.vm_name != "" ? var.vm_name : "tpl-parrot-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  extras_flag = var.extras == "" ? "" : (var.extras == "none" ? "--no-extras" : "--extras=${var.extras}")
  media       = trimsuffix(var.media_url, "/")
  media_env = local.media == "" ? "" : join(" ", [
    "WORDPRESS_URL=${local.media}/linux/wordpress/latest.tar.gz",
    "WP_CLI_URL=${local.media}/linux/wp-cli/wp-cli.phar",
    "NEXTCLOUD_URL=${local.media}/linux/nextcloud/latest.tar.bz2",
    "CHINOOK_URL=${local.media}/linux/chinook",
  ])
}

source "vsphere-clone" "parrot" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  template            = "${var.template_folder}/${var.base_vm}"
  vm_name             = local.vm_name
  linked_clone        = false
  notes               = "Parrot Security ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())} from ${var.base_vm}."

  CPUs = 2
  RAM  = 4096

  communicator = "ssh"
  ssh_username = var.image_user
  ssh_password = var.image_password
  ssh_timeout  = "20m"

  shutdown_command    = "sudo bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-clone.parrot"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/clean.sh"]
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo env ${local.media_env} bash /tmp/prepare.sh ${local.extras_flag}"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/parrot-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = var.extras
    }
  }
}
