#!/bin/sh
# Run by XCP-ng's installer once the new system's files are in place ($1: where it's mounted), from
# answers.pkrtpl.xml. XCP-ng's own repositories have no VMware Tools, and the template build (and the
# panel) need them to see the VM's address: dom0 is CentOS 7 underneath, so CentOS 7's open-vm-tools
# from the vault. And the build's SSH key for root.
set -e
root=$1
cp /etc/resolv.conf "$root/etc/resolv.conf"
cat >"$root/etc/yum.repos.d/lab-centos7-vault.repo" <<'REPO'
[lab-centos7-vault]
name=CentOS 7 (vault): VMware Tools for the lab template
baseurl=http://vault.centos.org/7.9.2009/os/x86_64/
gpgcheck=1
gpgkey=http://vault.centos.org/7.9.2009/os/x86_64/RPM-GPG-KEY-CentOS-7
enabled=0
REPO
chroot "$root" yum -y -q --disablerepo='*' --enablerepo=lab-centos7-vault install open-vm-tools
chroot "$root" systemctl enable vmtoolsd
mkdir -p "$root/root/.ssh"
echo "${ssh_public_key}" >"$root/root/.ssh/authorized_keys"
chmod 700 "$root/root/.ssh"
chmod 600 "$root/root/.ssh/authorized_keys"
