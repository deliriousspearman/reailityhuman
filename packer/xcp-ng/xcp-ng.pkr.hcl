# XCP-ng template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh xcp-ng -var http_ip=<this machine's address on the build network>
#
# A Xen hypervisor inside a VM: nested virtualisation is on. The installer reads answers.pkrtpl.xml
# from Packer's web server (typed onto GRUB's command line), and runs post-install.pkrtpl.sh, which adds
# VMware Tools (CentOS 7's: XCP-ng has none) and the build's SSH key. XCP-ng has no cloud-init for
# itself, so it gets the panel's data the way legacy Linux does (templates.yaml: family legacy):
# scripts/template/xcp-ng/lab-firstboot, which also rebuilds the management network on each clone's
# new adapter (XAPI ties it to the template's MAC address).

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
  default = "8.3"
}
variable "iso" {
  type    = string
  default = "xcp-ng-8.3.0-20260806.iso"
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
# The address the build VM reaches this machine's web server on: the answer file names its post-install
# script by URL, which Packer can only fill into the boot command, not into the files it serves.
variable "http_ip" { type = string }

locals {
  vm_name   = var.vm_name != "" ? var.vm_name : "tpl-xcp-ng-${var.version}-${formatdate("YYYYMMDD", timestamp())}"
  http_port = 8687
}

source "vsphere-iso" "xcpng" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "XCP-ng ${var.version} template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "centos7_64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 4096
  NestedHV             = true
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 65536
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths    = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  remove_cdrom = true

  http_ip       = var.http_ip
  http_port_min = local.http_port
  http_port_max = local.http_port
  http_content = {
    "/answers.xml" = templatefile("${path.root}/answers.pkrtpl.xml", {
      root_password    = var.build_password
      post_install_url = "http://${var.http_ip}:${local.http_port}/post-install.sh"
    })
    "/post-install.sh" = templatefile("${path.root}/post-install.pkrtpl.sh", {
      ssh_public_key = var.ssh_public_key
    })
  }

  # GRUB's command line: the installer's own "install" entry, with the answer file added.
  boot_order = "disk,cdrom"
  boot_wait  = "5s"
  boot_command = [
    "c<wait2>",
    "multiboot2 /boot/xen.gz dom0_max_vcpus=1-16 dom0_mem=max:2048M console=vga<enter><wait1>",
    "module2 /boot/vmlinuz console=tty0 answerfile=http://{{ .HTTPIP }}:{{ .HTTPPort }}/answers.xml install<enter><wait1>",
    "module2 /install.img<enter><wait1>",
    "boot<enter>",
  ]

  ip_wait_timeout      = "45m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "45m"

  shutdown_command    = "bash /tmp/xcp-ng/clean-xcp-ng.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.xcpng"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/template/xcp-ng"
    destination = "/tmp/"
  }

  provisioner "shell" {
    inline = ["bash /tmp/xcp-ng/prepare-xcp-ng.sh"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/xcp-ng-${var.version}.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
