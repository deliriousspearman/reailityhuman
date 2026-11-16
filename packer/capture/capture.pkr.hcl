# The packet capture appliance (backend/app/capture.py, docs/admin-guide.md "Packet capture"):
#
#   packer/build.sh capture -var panel_key="$(cat panel-key.pub)"
#
# An Alpine VM, not a template, left powered off in Labs/Capture as lab-capture: power it on and set
# CAPTURE_VM in lab-deploy.env. Its first network adapter is on the LAN (DHCP), for the panel's SSH;
# the second is on the capture port group (LAN's VLAN, promiscuous mode on), with no address, where
# tcpdump listens. panel_key is the panel's public key (the Admin page shows it): root's only key once
# built, and it may only run lab-capture (scripts/capture/lab-capture).
#
# The install is packer/alpine's (its answer file and boot steps); then scripts/capture/prepare-capture.sh
# and, as the shutdown, finish-capture.sh.
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
# Where the appliance goes, and its second adapter's port group.
variable "capture_folder" {
  type    = string
  default = "Labs/Capture"
}
variable "capture_network" {
  type    = string
  default = "LAN-capture"
}
variable "panel_key" {
  type        = string
  description = "The panel's public key for the appliance (Admin page, Packet capture)"
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
  default = "3.24"
}
variable "iso" {
  type    = string
  default = "alpine-virt-3.24.3-x86_64.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
# Offline: the media folder (scripts/isos/fetch-media.sh), whose linux/alpine apk repository goes on the
# build CD; everything is installed from it, and the result points at Alpine's own repositories again.
variable "media_dir" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  offline  = var.media_dir != ""
  apk_repo = "/media/lab/alpine/v${var.version}"
  vm_name = var.vm_name != "" ? var.vm_name : "lab-capture"
}

source "vsphere-iso" "capture" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.capture_folder
  vm_name             = local.vm_name
  notes               = "lab-deploy's packet capture appliance (Alpine Linux ${var.version}), built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}. Its second adapter listens on ${var.capture_network}."

  guest_os_type        = "other5xLinux64Guest"
  firmware             = "efi"
  CPUs                 = 1
  RAM                  = 512
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 4096
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }
  network_adapters {
    network      = var.capture_network
    network_card = "vmxnet3"
  }

  iso_paths = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  cd_label  = "LABBUILD"
  cd_content = {
    "answers" = templatefile("${path.root}/../alpine/answers.pkrtpl", { ssh_public_key = var.ssh_public_key, apk_repos = local.offline ? "/media/sr0/apks ${local.apk_repo}" : "-1 -c" })
  }
  # Offline: the media folder's apk repository, as /alpine on the CD (Packer keeps an absolute path's last folder).
  cd_files = local.offline ? ["${var.media_dir}/linux/alpine"] : []
  remove_cdrom = true

  # The live system's login prompt, then setup-alpine from the build CD, with root's password empty
  # (-e: root signs in with the build key only) and the disk left out. VMware Tools go into the live
  # system next, so it reports its address to Packer; setup-disk then installs it all on the disk,
  # Tools included (it takes the live system's packages and settings), without asking (ERASE_DISKS).
  boot_wait = "30s"
  boot_command = concat([
    "root<enter><wait3>",
    "mkdir -p /media/lab && mount -t iso9660 $(findfs LABEL=LABBUILD) /media/lab<enter><wait2>",
    ], local.offline ? ["cp /media/lab/alpine/keys/lab-media.rsa.pub /etc/apk/keys/<enter><wait2>"] : [], [
    "setup-alpine -e -f /media/lab/answers && apk add -q open-vm-tools open-vm-tools-guestinfo && rc-update add open-vm-tools default && rc-service open-vm-tools start && ",
    "ERASE_DISKS=/dev/sda setup-disk -m sys /dev/sda && umount /media/lab && reboot<enter>",
  ])

  ip_wait_timeout      = "30m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "30m"

  shutdown_command    = "sh /tmp/capture/finish-capture.sh"
  shutdown_timeout    = "10m"
  convert_to_template = false
}

build {
  sources = ["source.vsphere-iso.capture"]

  provisioner "file" {
    source      = "${path.root}/../../scripts/capture"
    destination = "/tmp/"
  }
  provisioner "shell" {
    inline           = ["sh /tmp/capture/prepare-capture.sh"]
    environment_vars = concat(["PANEL_KEY=${var.panel_key}"], local.offline ? ["LAB_APK_REPO=${local.apk_repo}"] : [])
    execute_command  = "chmod +x {{ .Path }}; env {{ .Vars }} sh {{ .Path }}"
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/capture.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
    }
  }
}
