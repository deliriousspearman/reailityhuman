#!/usr/bin/env bash
# Removes a prepared TrueNAS SCALE VM's identity and the build's access, then powers it off, ready to
# become a panel template (packer/truenas-scale runs it with sudo as the build's shutdown):
#
#   sudo bash clean-truenas.sh --yes
#
# It locks truenas_admin (no password, no key, sudo with a password again: each machine sets its own
# from lab-firstboot), deletes the SSH host keys (lab-firstboot makes each machine its own), and puts
# the hostname back; then the panel's first-boot markers, logs and history.
set -euo pipefail

[[ ${1:-} == --yes ]] || { echo "This locks truenas_admin and powers the VM off: run it with --yes." >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Run this with sudo." >&2; exit 1; }

echo "==> truenas_admin: no password, no key"
id=$(midclt call user.query '[["username", "=", "truenas_admin"]]' '{"get": true}' | jq .id)
midclt call user.update "$id" '{"sshpubkey": null, "sudo_commands_nopasswd": []}' >/dev/null
midclt call datastore.update account.bsdusers "$id" '{"bsdusr_unixhash": "*", "bsdusr_smbhash": "*"}' >/dev/null
midclt call etc.generate shadow >/dev/null

echo "==> Identity and traces"
midclt call network.configuration.update '{"hostname": "truenas"}' >/dev/null
midclt call datastore.update services.ssh 1 '{"ssh_host_rsa_key": null, "ssh_host_rsa_key_pub": null, "ssh_host_ecdsa_key": null, "ssh_host_ecdsa_key_pub": null, "ssh_host_ed25519_key": null, "ssh_host_ed25519_key_pub": null}' >/dev/null
rm -f /etc/ssh/ssh_host_* /var/lib/lab-deploy/instance /var/lib/lab-deploy/extras.status
rm -rf /var/log/lab-deploy /tmp/truenas /root/.bash_history /home/truenas_admin/.zsh_history
{ journalctl --rotate && journalctl --vacuum-time=1s; } >/dev/null 2>&1 || true
echo "cleaned=$(date -u +%Y-%m-%dT%H:%MZ)" >>/root/lab-template

echo "==> Powering off"
sync
systemctl poweroff
