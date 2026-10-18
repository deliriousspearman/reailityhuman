# Windows Server 2025 templates for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh windows-server                       # Desktop Experience, with Outlook and SQL Server
#   packer/build.sh windows-server -var edition=core     # Server Core, with SQL Server
#
# Installs from the evaluation ISO with autounattend.xml, installs VMware Tools and opens WinRM
# (bootstrap.ps1), runs scripts/template/prepare.ps1 (provision.ps1 gathers Cloudbase-Init, Office's
# files and SQL Server's), then clean.ps1's sysprep as the shutdown (finish.ps1), and leaves a template
# in Labs/Templates with its "clean" snapshot: docs/setup-vsphere.md part 5, by hand.

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
variable "edition" {
  type    = string
  default = "desktop"
  validation {
    condition     = contains(["desktop", "core"], var.edition)
    error_message = "The edition is desktop or core."
  }
}
# The ISOs' names in the datastore's ISO folder (scripts/isos/isos.txt).
variable "iso" {
  type    = string
  default = "windows-server-2025-eval-26100.1742.iso"
}
variable "sql_server_iso" {
  type    = string
  default = "SQLServer2025-x64-ENU-EntDev.iso"
}
# What to bake in: the Outlook extra's Office files (desktop only), SQL Server's media.
variable "office" {
  type    = bool
  default = true
}
variable "sql_server" {
  type    = bool
  default = true
}
# Offline builds: the media folder scripts/isos/fetch-media.sh makes (its windows\ part goes on the
# build's CD): Cloudbase-Init, Office's files, Chinook. Empty: downloaded during the build.
variable "media_dir" {
  type    = string
  default = ""
}
variable "vm_name" {
  type    = string
  default = ""
}
# Administrator's password while building (build.sh makes a random one). Clones have the built-in
# Administrator disabled.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  core       = var.edition == "core"
  suffix     = local.core ? "-core" : ""
  vm_name    = var.vm_name != "" ? var.vm_name : "tpl-windows-server-2025${local.suffix}-${formatdate("YYYYMMDD", timestamp())}"
  image_name = local.core ? "Windows Server 2025 Standard Evaluation" : "Windows Server 2025 Standard Evaluation (Desktop Experience)"
  office     = var.office && !local.core
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
  notes               = "Windows Server 2025 (${var.edition}) template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "windows2022srvNext_64Guest"
  firmware             = "efi-secure"
  CPUs                 = 2
  RAM                  = local.core ? 2048 : 4096
  disk_controller_type = ["nvme"]
  storage {
    disk_size             = local.core ? 40960 : 61440
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
      "${path.root}/bootstrap.ps1",
      "${path.root}/provision.ps1",
      "${path.root}/finish.ps1",
      "${path.root}/../../scripts/template/prepare.ps1",
      "${path.root}/../../scripts/template/clean.ps1",
      "${path.root}/../../scripts/template/office/download.xml",
    ],
    var.media_dir != "" ? ["${var.media_dir}/windows"] : [],
  )
  cd_content = {
    "autounattend.xml" = templatefile("${path.root}/autounattend.pkrtpl.xml", {
      image_name     = local.image_name
      admin_password = var.build_password
      client         = false
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
    script = "${path.root}/provision.ps1"
    environment_vars = [
      "LAB_EDITION=${var.edition}",
      "LAB_OFFICE=${local.office ? "yes" : "no"}",
      "LAB_SQLSERVER=${var.sql_server ? "yes" : "no"}",
    ]
    elevated_user     = "Administrator"
    elevated_password = var.build_password
  }

  # Straight on to sysprep, as by hand: no restart, which would also run Cloudbase-Init on the
  # template itself (and once left WinRM refusing Packer's shutdown command).

  post-processor "manifest" {
    output     = "${path.root}/../output/windows-server-2025${local.suffix}.json"
    strip_path = true
    custom_data = {
      vm_name    = local.vm_name
      office     = local.office
      sql_server = var.sql_server
    }
  }
}
