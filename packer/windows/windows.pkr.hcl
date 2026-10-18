# Windows 11 Enterprise (90-day evaluation) template for the panel, built unattended
# (docs/build-templates.md):
#
#   packer/build.sh windows        # with Outlook's and SQL Server's files
#
# The same build as ../windows-server (its autounattend.xml with client = true, and its bootstrap.ps1,
# provision.ps1 and finish.ps1), with Windows 11's differences:
#   - no virtual TPM: Setup's TPM, Secure Boot, CPU and RAM checks are skipped (LabConfig), so clones
#     need no key provider in vCenter; BitLocker, Credential Guard and Windows Hello for Business
#     aren't available on them;
#   - the built-in Administrator is switched on for the build (client Windows has it off); clones have
#     it disabled again by the panel's first-boot script, as on Server;
#   - the Store doesn't install or update apps (they would stop sysprep).
# The evaluation lasts 90 days: rebuild the template before it runs out.

packer {
  required_plugins {
    vsphere = {
      source  = "github.com/hashicorp/vsphere"
      version = "~> 2.5"
    }
  }
}

# vCenter and where things go: packer/lab.pkrvars.hcl; the account from the environment (build.sh).
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
# Only the Linux builds use these.
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

# This build
variable "version" {
  type    = string
  default = "11"
}
# The ISOs' names in the datastore's ISO folder (scripts/isos/isos.txt).
variable "iso" {
  type    = string
  default = "windows-11-enterprise-eval-26300.9457.iso"
}
variable "image_name" {
  type    = string
  default = "Windows 11 Enterprise Evaluation"
}
variable "sql_server_iso" {
  type    = string
  default = "SQLServer2025-x64-ENU-EntDev.iso"
}
# What to bake in: the Outlook extra's Office files, SQL Server's media.
variable "office" {
  type    = bool
  default = true
}
variable "sql_server" {
  type    = bool
  default = true
}
# Offline builds: the media folder scripts/isos/fetch-media.sh makes (its windows\ part goes on the
# build's CD). Empty: downloaded during the build.
variable "media_dir" {
  type    = string
  default = ""
}
variable "vm_name" {
  type    = string
  default = ""
}
# Administrator's password while building (build.sh makes a random one).
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  scripts = "${path.root}/../windows-server"
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-windows-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  iso_paths = concat(
    ["[${var.datastore}] ${var.iso_folder}/${var.iso}", "[] /vmimages/tools-isoimages/windows.iso"],
    var.sql_server ? ["[${var.datastore}] ${var.iso_folder}/${var.sql_server_iso}"] : [],
  )
}

source "vsphere-iso" "windows" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "Windows ${var.version} Enterprise evaluation template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "windows11_64Guest"
  firmware             = "efi-secure"
  CPUs                 = 2
  RAM                  = 4096
  disk_controller_type = ["nvme"]
  storage {
    disk_size             = 65536
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  cdrom_type = "sata"
  iso_paths  = local.iso_paths
  cd_label   = "LABBUILD"
  cd_files = concat(
    [
      "${local.scripts}/bootstrap.ps1",
      "${local.scripts}/provision.ps1",
      "${local.scripts}/finish.ps1",
      "${path.root}/../../scripts/template/prepare.ps1",
      "${path.root}/../../scripts/template/clean.ps1",
      "${path.root}/../../scripts/template/office/download.xml",
    ],
    var.media_dir != "" ? ["${var.media_dir}/windows"] : [],
  )
  cd_content = {
    "autounattend.xml" = templatefile("${local.scripts}/autounattend.pkrtpl.xml", {
      image_key      = "/IMAGE/NAME"
      image_name     = var.image_name
      admin_password = var.build_password
      client         = true
    })
  }
  remove_cdrom = true

  # An empty disk falls through to the CD, whose loader waits for a key press.
  boot_order   = "disk,cdrom"
  boot_wait    = "2s"
  boot_command = ["<spacebar><wait1><spacebar><wait1><spacebar><wait1><spacebar>"]

  ip_wait_timeout = "90m"
  communicator    = "winrm"
  winrm_username  = "Administrator"
  winrm_password  = var.build_password
  winrm_timeout   = "2h"

  # finish.ps1 runs clean.ps1, whose sysprep shuts the VM down.
  shutdown_command    = "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\LabBuild\\finish.ps1"
  shutdown_timeout    = "45m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.windows"]

  provisioner "powershell" {
    script = "${local.scripts}/provision.ps1"
    environment_vars = [
      "LAB_EDITION=desktop",
      "LAB_OFFICE=${var.office ? "yes" : "no"}",
      "LAB_SQLSERVER=${var.sql_server ? "yes" : "no"}",
    ]
    elevated_user     = "Administrator"
    elevated_password = var.build_password
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/windows-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name    = local.vm_name
      office     = var.office
      sql_server = var.sql_server
    }
  }
}
