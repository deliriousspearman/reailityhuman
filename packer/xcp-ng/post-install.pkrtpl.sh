#!/bin/sh
# Run by XCP-ng's installer once the new system's files are in place ($1: where it's mounted), from
# answers.pkrtpl.xml. XCP-ng's own repositories have no VMware Tools, and the template build (and the
# panel) need them to see the VM's address: dom0 is CentOS 7 underneath, so CentOS 7's open-vm-tools
# from the vault (or a LAN mirror of it: the build's vault variable). And the build's SSH key for root.
set -e
root=$1
cp /etc/resolv.conf "$root/etc/resolv.conf"
cat >"$root/etc/yum.repos.d/lab-centos7-vault.repo" <<'REPO'
[lab-centos7-vault]
name=CentOS 7 (vault): VMware Tools for the lab template
baseurl=${vault}/os/x86_64/
gpgcheck=1
gpgkey=${vault}/os/x86_64/RPM-GPG-KEY-CentOS-7
enabled=0
REPO
chroot "$root" yum -y -q --disablerepo='*' --enablerepo=lab-centos7-vault install open-vm-tools
chroot "$root" systemctl enable vmtoolsd
# Its service starts only where systemd detects VMware, and dom0 runs under Xen (systemd sees none).
mkdir -p "$root/etc/systemd/system/vmtoolsd.service.d"
printf '[Unit]\nConditionVirtualization=\n' >"$root/etc/systemd/system/vmtoolsd.service.d/lab.conf"
mkdir -p "$root/root/.ssh"
echo "${ssh_public_key}" >"$root/root/.ssh/authorized_keys"
chmod 700 "$root/root/.ssh"
chmod 600 "$root/root/.ssh/authorized_keys"
