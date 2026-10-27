#!/usr/bin/env bash
# Runs in CachyOS's live system, as root over SSH (packer/cachyos/cachyos.pkr.hcl): installs CachyOS on
# the VM's disk with CachyOS's own installer, unattended (cachyos-installer's headless mode), then
# readies the new system for the rest of the build: SSH and VMware Tools on, root signing in with the
# build's key, the build user (the installer's user) able to sudo. The build reboots into it next.
#
#   BUILD_PASSWORD=<password> SSH_PUBLIC_KEY=<key> bash install.sh
#
# What the installer makes is CachyOS's own desktop install: KDE Plasma, Btrfs with CachyOS's
# subvolumes, its Limine boot loader (also on the EFI fallback path, so clones boot without the
# template's boot entries), and its repositories as the live system has them: the generic x86-64 ones,
# so machines run on any x86-64 host (not the x86-64-v3/v4 builds, which need newer CPUs).
set -euo pipefail

: "${BUILD_PASSWORD:?}" "${SSH_PUBLIC_KEY:?}"
disk=/dev/sda

# The live system's own start-up first (pacman-init fills its keyring).
systemctl is-system-running --wait >/dev/null || true

# The build's password is letters, digits and hyphens (build.sh), so it needs no JSON escaping.
cat >/root/settings.json <<EOF
{
  "install_type": "simple",
  "headless_mode": true,
  "device": "$disk",
  "fs_name": "btrfs",
  "subvolumes": "default",
  "partitions": [
    {"name": "${disk}1", "mountpoint": "/boot", "size": "2G", "fs_name": "vfat", "type": "boot"},
    {"name": "${disk}2", "mountpoint": "/", "size": "100%", "type": "root"}
  ],
  "hostname": "tpl-cachyos",
  "timezone": "UTC",
  "user_name": "builder",
  "user_pass": "$BUILD_PASSWORD",
  "user_shell": "/bin/bash",
  "root_pass": "$BUILD_PASSWORD",
  "desktop": "kde",
  "bootloader": "limine",
  "os_prober": false
}
EOF

echo "==> CachyOS's installer (headless)"
cachyos-installer --config /root/settings.json

echo "==> Readying the new system for the build"
mount -o subvol=/@ "${disk}2" /mnt
mount "${disk}1" /mnt/boot
arch-chroot /mnt pacman -S --needed --noconfirm openssh open-vm-tools
arch-chroot /mnt systemctl enable sshd.service vmtoolsd.service vmware-vmblock-fuse.service
# The installer switches its firewall (ufw) on, which would keep the build out: prepare.sh switches it
# back on with SSH allowed.
if [[ -e /mnt/usr/lib/systemd/system/ufw.service ]]; then
	arch-chroot /mnt systemctl disable ufw.service
fi
install -d -m 700 /mnt/root/.ssh
printf '%s\n' "$SSH_PUBLIC_KEY" >/mnt/root/.ssh/authorized_keys
chmod 600 /mnt/root/.ssh/authorized_keys
echo 'builder ALL=(ALL) NOPASSWD:ALL' >/mnt/etc/sudoers.d/builder
chmod 440 /mnt/etc/sudoers.d/builder
# Limine remembers the last entry booted (in an EFI variable) and has no default otherwise: with none
# saved, as on every clone's first boot, it stops at its menu on the CachyOS folder. Boot the first
# kernel instead (entry 2, inside that folder) after its 5 s. prepare.sh keeps it so.
sed -i -e '/^remember_last_entry:/d' -e '/^default_entry:/d' -e '/^timeout:/a default_entry: 2' /mnt/boot/limine.conf
umount -R /mnt
echo "==> Installed"
