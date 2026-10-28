# Windows Server templates for the panel (2025, 2022, 2019, 2016 or 2012 R2), built unattended
# (docs/build-templates.md):
#
#   packer/build.sh windows-server                       # Desktop Experience, with Outlook and SQL Server
#   packer/build.sh windows-server -var edition=core     # Server Core, with SQL Server
#   packer/build.sh windows-server -var version=2022     # 2022 or 2019 (either edition): their evaluations
#   packer/build.sh windows-server -var version=2016     # 2016 or 2012r2: no Office or SQL Server (neither
#                                                        # supports them); legacy.ps1 adds what they lack
#   packer/windows-server/fetch-legacy.sh                # once, before 2012r2: its files, for the CD
#
# Installs from the evaluation ISO with autounattend.xml, installs VMware Tools and opens WinRM
# (bootstrap.ps1), adds what 2016 and 2012 R2 lack (legacy.ps1, then a restart), runs scripts/template/prepare.ps1 (provision.ps1 gathers Cloudbase-Init, Office's
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
variable "version" {
  type    = string
  default = "2025"
  validation {
    condition     = contains(["2025", "2022", "2019", "2016", "2012r2"], var.version)
    error_message = "The version is 2025, 2022, 2019, 2016 or 2012r2."
  }
}
# Empty: the version's evaluation ISO, named as in isos.txt.
variable "iso" {
  type    = string
  default = ""
}
variable "sql_server_iso" {
  type    = string
  default = "SQLServer2025-x64-ENU-EntDev.iso"
}
# What to bake in: the Outlook extra's Office files (desktop only), SQL Server's media. Neither on 2016
# or 2012 R2: Microsoft 365 Apps and SQL Server 2025 don't support them.
variable "office" {
  type    = bool
  default = true
}
variable "sql_server" {
  type    = bool
  default = true
}
# The Exchange template (desktop only): Exchange Server SE's files and its prerequisites, for the
# Exchange extra. Built as its own template (-var exchange=true -var office=false -var sql_server=false):
# Exchange wants a machine of its own.
variable "exchange" {
  type    = bool
  default = false
}
variable "exchange_iso" {
  type    = string
  default = "ExchangeServerSE-x64.iso"
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
  core    = var.edition == "core"
  suffix  = local.core ? "-core" : ""
  suffix2 = var.exchange ? "-exchange" : local.suffix
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-windows-server-${var.version}${local.suffix2}-${formatdate("YYYYMMDD", timestamp())}"
  # 2016 and 2012 R2: what legacy.ps1 adds, and nothing baked in that they don't support.
  legacy = contains(["2016", "2012r2"], var.version)
  # 2025's images go by these names; the older ones have other names inside (Setup then asks), so
  # those go by number: 1 Standard (Core), 2 Standard (Desktop Experience; on 2012 R2, "with a GUI").
  image_key  = var.version == "2025" ? "/IMAGE/NAME" : "/IMAGE/INDEX"
  image_name = var.version != "2025" ? (local.core ? "1" : "2") : (local.core ? "Windows Server 2025 Standard Evaluation" : "Windows Server 2025 Standard Evaluation (Desktop Experience)")
  iso = var.iso != "" ? var.iso : {
    "2025"   = "windows-server-2025-eval-26100.1742.iso"
    "2022"   = "windows-server-2022-eval.iso"
    "2019"   = "windows-server-2019-eval.iso"
    "2016"   = "windows-server-2016-eval.iso"
    "2012r2" = "windows-server-2012r2-eval.iso"
  }[var.version]
  guest_os_type = {
    "2025"   = "windows2022srvNext_64Guest"
    "2022"   = "windows2019srvNext_64Guest"
    "2019"   = "windows2019srv_64Guest"
    "2016"   = "windows9Server64Guest"
    "2012r2" = "windows8Server64Guest"
  }[var.version]
  # The CD's windows folder: an offline build's media folder; else, for 2012 R2 (which can't download
  # them: its TLS is too old), what fetch-legacy.sh downloaded, which 2016 uses too when it's there.
  legacy_media = "${path.root}/media/windows"
  media = var.media_dir != "" ? ["${var.media_dir}/windows"] : (
    var.version == "2012r2" || (local.legacy && fileexists("${local.legacy_media}/cloudbase-init/CloudbaseInitSetup_x64.msi")) ? [local.legacy_media] : []
  )
  office     = var.office && !local.core && !local.legacy
  sql_server = var.sql_server && !local.legacy
  iso_paths = concat(
    ["[${var.datastore}] ${var.iso_folder}/${local.iso}", "[] /vmimages/tools-isoimages/windows.iso"],
    local.sql_server ? ["[${var.datastore}] ${var.iso_folder}/${var.sql_server_iso}"] : [],
    var.exchange ? ["[${var.datastore}] ${var.iso_folder}/${var.exchange_iso}"] : [],
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
  notes               = "Windows Server ${var.version} (${var.edition}) template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = local.guest_os_type
  firmware             = "efi-secure"
  CPUs                 = 2
  RAM                  = local.core ? 2048 : 4096
  disk_controller_type = ["nvme"]
  storage {
    disk_size             = var.exchange ? 102400 : (local.core ? 40960 : 61440)
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
    local.media,
  )
  cd_content = {
    "autounattend.xml" = templatefile("${path.root}/autounattend.pkrtpl.xml", {
      image_key      = local.image_key
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

  # 2016 and 2012 R2: OpenSSH, and on 2012 R2 PowerShell 5.1 and what it and Cloudbase-Init need. On
  # 2019 and later it says so and does nothing, and the restart is only an echo.
  provisioner "powershell" {
    script            = "${path.root}/legacy.ps1"
    elevated_user     = "Administrator"
    elevated_password = var.build_password
  }
  provisioner "windows-restart" {
    restart_command = local.legacy ? "shutdown /r /f /t 5 /c \"Packer: legacy.ps1's updates\"" : "cmd /c echo No restart needed"
    restart_timeout = "30m"
  }

  provisioner "powershell" {
    script = "${path.root}/provision.ps1"
    environment_vars = [
      "LAB_EDITION=${var.edition}",
      "LAB_OFFICE=${local.office ? "yes" : "no"}",
      "LAB_SQLSERVER=${local.sql_server ? "yes" : "no"}",
      "LAB_EXCHANGE=${var.exchange ? "yes" : "no"}",
    ]
    elevated_user     = "Administrator"
    elevated_password = var.build_password
  }

  # Straight on to sysprep, as by hand: no restart, which would also run Cloudbase-Init on the
  # template itself (and once left WinRM refusing Packer's shutdown command).

  post-processor "manifest" {
    output     = "${path.root}/../output/windows-server-${var.version}${local.suffix2}.json"
    strip_path = true
    custom_data = {
      vm_name    = local.vm_name
      office     = local.office
      sql_server = local.sql_server
    }
  }
}
