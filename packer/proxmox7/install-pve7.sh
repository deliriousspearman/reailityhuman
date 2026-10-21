#!/usr/bin/env bash
# Installs Proxmox VE 7 on the Debian 11 the build just installed (packer/proxmox7), as Proxmox
# documents: its repository and key, a full upgrade, then proxmox-ve. Run as root. LAB_PROXMOX_MIRROR: a
# LAN mirror of download.proxmox.com/debian (offline builds). The repository's key is the one beside this
# script (Proxmox's, SHA-512 7fb03ec8a1675723d2853b84aa4fdb49a46a3bb72b9951361488bfd19b29aab0a789a4f8c7406e71a69aabbc727c936d3549731c4659ffa1a08f44db8fdcebfa).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Proxmox needs the host's name to resolve to its own address, not 127.0.1.1.
ip=$(ip -4 -o route get 1.1.1.1 | sed -n 's/.* src \([0-9.]*\).*/\1/p')
host=$(hostname)
sed -i -E "/[[:space:]]$host([.[:space:]]|\$)/d" /etc/hosts
echo "$ip $host.lab.example $host" >>/etc/hosts

# Debian's installer adds an "inet6 auto" stanza, which ifupdown2 (Proxmox's) rejects, failing its
# install. prepare-proxmox.sh writes the network config afresh afterwards anyway.
sed -i '/inet6 auto/d' /etc/network/interfaces
install -m 644 "$(dirname "$0")/proxmox-release-bullseye.gpg" /etc/apt/trusted.gpg.d/proxmox-release-bullseye.gpg
mirror=${LAB_PROXMOX_MIRROR:-http://download.proxmox.com/debian}
echo "deb ${mirror%/}/pve bullseye pve-no-subscription" >/etc/apt/sources.list.d/pve-no-subscription.list
apt-get -q update
apt-get -yq -o Dpkg::Options::=--force-confold full-upgrade
# Postfix as local-only mail (Proxmox's notifications), without questions.
echo "postfix postfix/main_mailer_type select Local only" | debconf-set-selections
echo "postfix postfix/mailname string $host.lab.example" | debconf-set-selections
apt-get -yq -o Dpkg::Options::=--force-confold install proxmox-ve postfix open-iscsi chrony
# Debian's kernel and os-prober, as Proxmox advises.
apt-get -yq remove os-prober
apt-get -yq remove 'linux-image-amd64' 'linux-image-5.10*' || true
update-grub
echo "Proxmox VE $(pveversion | sed -E 's|^pve-manager/([^/]+)/.*|\1|') installed."
