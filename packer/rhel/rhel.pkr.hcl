# RHEL-family templates for the panel (CentOS Stream, Rocky Linux, AlmaLinux), built unattended
# (docs/build-templates.md):
#
#   packer/build.sh rhel -var distro=rocky          # Rocky Linux 9
#   packer/build.sh rhel -var distro=alma           # AlmaLinux 9
#   packer/build.sh rhel -var distro=centos-stream  # CentOS Stream 9
#
# Installs from the distribution's boot ISO with a kickstart (ks.pkrtpl.cfg, on a CD labelled OEMDRV,
# which the installer reads by itself), packages from its repositories, then runs
# scripts/template/prepare.sh and clean.sh as for Ubuntu, and leaves a template in Labs/Templates with
# its "clean" snapshot.

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
# Offline: where the media folder from scripts/isos/fetch-media.sh is served (its linux/ part); the
# RHEL family's extras (web servers) don't download anything yet, so it's for later ones.
variable "media_url" {
  type    = string
  default = ""
}
# Offline: a LAN mirror of the distribution's repositories, as the base holding BaseOS/ and AppStream/
# (e.g. http://mirror.lab.example/rocky/9). Empty: the distribution's own.
variable "repo_mirror" {
  type    = string
  default = ""
}

variable "distro" {
  type    = string
  default = "rocky"
  validation {
    condition     = contains(["centos-stream", "rocky", "alma"], var.distro)
    error_message = "The distro is centos-stream, rocky or alma."
  }
}
variable "version" {
  type    = string
  default = "9"
}
# The boot ISO's name in the datastore's ISO folder (scripts/isos/isos.txt); default by distro.
variable "iso" {
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
# The build user's password (build.sh makes a random one); it signs in with its key.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  isos = {
    "centos-stream" = "CentOS-Stream-9-latest-x86_64-boot.iso"
    "rocky"         = "Rocky-9.8-x86_64-boot.iso"
    "alma"          = "AlmaLinux-9.8-x86_64-boot.iso"
  }
  repos = {
    "centos-stream" = "https://mirror.stream.centos.org/${var.version}-stream"
    "rocky"         = "https://dl.rockylinux.org/pub/rocky/${var.version}"
    "alma"          = "https://repo.almalinux.org/almalinux/${var.version}"
  }
  guest_ids = {
    "centos-stream" = "centos9_64Guest"
    "rocky"         = "rockylinux_64Guest"
    "alma"          = "almalinux_64Guest"
  }
  repo        = trimsuffix(var.repo_mirror != "" ? var.repo_mirror : local.repos[var.distro], "/")
  iso         = var.iso != "" ? var.iso : local.isos[var.distro]
  vm_name     = var.vm_name != "" ? var.vm_name : "tpl-${var.distro}-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  extras_flag = var.extras == "" ? "" : (var.extras == "none" ? "--no-extras" : "--extras=${var.extras}")
}

source "vsphere-iso" "rhel" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "${var.distro} ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = local.guest_ids[var.distro]
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

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${local.iso}"]
  # The installer reads ks.cfg from a volume labelled OEMDRV by itself.
  cd_label = "OEMDRV"
  cd_content = {
    "ks.cfg" = templatefile("${path.root}/ks.pkrtpl.cfg", {
      distro         = var.distro
      baseos         = "${local.repo}/BaseOS/x86_64/os/"
      appstream      = "${local.repo}/AppStream/x86_64/os/"
      build_password = var.build_password
      ssh_public_key = var.ssh_public_key
    })
  }
  remove_cdrom = true

  # GRUB's default entry checks the media first: go up to the plain install.
  boot_wait    = "5s"
  boot_command = ["<up><wait><enter>"]

  ip_wait_timeout      = "60m"
  communicator         = "ssh"
  ssh_username         = "builder"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "60m"

  shutdown_command    = "sudo bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.rhel"]

  provisioner "file" {
    sources     = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/clean.sh"]
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["sudo bash /tmp/prepare.sh ${local.extras_flag}"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/${var.distro}-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = var.extras
    }
  }
}
