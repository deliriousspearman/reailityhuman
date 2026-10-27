# CachyOS template for the panel, built unattended (docs/build-templates.md):
#
#   packer/build.sh cachyos
#
# Boots CachyOS's live ISO with the build's SSH key for root (a systemd credential on the kernel
# command line, which the live system's tmpfiles writes to /root/.ssh/authorized_keys), and without its
# desktop. Over SSH, install.sh runs CachyOS's own installer unattended (KDE Plasma, Btrfs, Limine) and
# readies the new system; the build reboots into it, runs scripts/template/prepare.sh, and clean.sh as
# its shutdown, leaving a template in Labs/Templates with its "clean" snapshot. CachyOS is rolling: each
# build is CachyOS as of that day.

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
variable "media_url" {
  type    = string
  default = ""
}

# The live ISO's name in the datastore's ISO folder (scripts/isos/isos.txt).
variable "iso" {
  type    = string
  default = "cachyos-desktop-linux-260809.iso"
}
variable "vm_name" {
  type    = string
  default = ""
}
variable "ssh_private_key_file" { type = string }
variable "ssh_public_key" { type = string }
# The build user's password (build.sh makes a random one), and root's until the build locks it.
variable "build_password" {
  type      = string
  sensitive = true
}

locals {
  vm_name = var.vm_name != "" ? var.vm_name : "tpl-cachyos-rolling-${formatdate("YYYYMMDD", timestamp())}"
}

source "vsphere-iso" "cachyos" {
  vcenter_server      = var.vcenter_server
  username            = var.vcenter_username
  password            = var.vcenter_password
  insecure_connection = var.vcenter_insecure
  datacenter          = var.datacenter
  cluster             = var.cluster
  datastore           = var.datastore
  folder              = var.template_folder
  vm_name             = local.vm_name
  notes               = "CachyOS (rolling) template for lab-deploy, built by Packer on ${formatdate("YYYY-MM-DD", timestamp())}."

  guest_os_type        = "other6xLinux64Guest"
  firmware             = "efi"
  CPUs                 = 2
  RAM                  = 4096
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = 40960
    disk_thin_provisioned = true
  }
  network_adapters {
    network      = var.network
    network_card = "vmxnet3"
  }

  iso_paths    = ["[${var.datastore}] ${var.iso_folder}/${var.iso}"]
  remove_cdrom = true

  # GRUB's menu shows about a second after power-on with CachyOS's entry selected, and boots it after
  # 10 s. Edit the entry (e): its linux line is the fourth (after setparams, a blank line and set
  # gfxpayload), and GRUB's graphical terminal drops keys that come too fast, so one Down at a time.
  # At the line's end go the root key, no desktop (multi-user), and the ISO left on the CD rather than
  # copied to memory.
  boot_wait = "5s"
  boot_command = [
    "e<wait><down><wait><down><wait><down><wait><end><wait>",
    " copytoram=n systemd.unit=multi-user.target",
    " systemd.set_credential_binary=ssh.authorized_keys.root:${base64encode(var.ssh_public_key)}",
    "<f10>",
  ]

  ip_wait_timeout      = "30m"
  communicator         = "ssh"
  ssh_username         = "root"
  ssh_private_key_file = var.ssh_private_key_file
  ssh_timeout          = "30m"

  # Root's key and password go before clean.sh deletes the build user and powers off.
  shutdown_command    = "rm -f /root/.ssh/authorized_keys && passwd -l root >/dev/null && BUILD_USER=builder bash /tmp/clean.sh --yes"
  shutdown_timeout    = "15m"
  create_snapshot     = true
  snapshot_name       = "clean"
  convert_to_template = true
}

build {
  sources = ["source.vsphere-iso.cachyos"]

  # In the live system: install, then reboot into the new system.
  provisioner "file" {
    source      = "${path.root}/install.sh"
    destination = "/root/install.sh"
  }
  provisioner "shell" {
    environment_vars = ["BUILD_PASSWORD=${var.build_password}", "SSH_PUBLIC_KEY=${var.ssh_public_key}"]
    inline           = ["bash /root/install.sh"]
  }
  # skip_clean: the session's gone before Packer could delete its script.
  provisioner "shell" {
    inline            = ["systemctl --no-block reboot"]
    expect_disconnect = true
    skip_clean        = true
  }

  # In the installed system (long enough after the reboot not to find the live one still there).
  provisioner "file" {
    pause_before = "90s"
    sources      = ["${path.root}/../../scripts/template/prepare.sh", "${path.root}/../../scripts/template/clean.sh"]
    destination  = "/tmp/"
  }
  provisioner "shell" {
    inline = ["bash /tmp/prepare.sh --no-extras"]
  }

  post-processor "manifest" {
    output     = "${path.root}/../output/cachyos-rolling.json"
    strip_path = true
    custom_data = {
      vm_name = local.vm_name
      extras  = "none"
    }
  }
}
