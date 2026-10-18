#!/bin/vbash
# Readies an installed VyOS VM to become a panel template, then powers it off (packer/vyos runs it as
# the build's shutdown, as the vyos user, from this folder copied to /tmp/vyos):
#
#   vbash clean-vyos.sh --yes
#
# Through VyOS's configuration commands (a vbash script with VyOS's script-template, the documented way
# to configure it from a script, which also works over a non-interactive SSH session): the vyos user
# gets a random password nobody knows (each machine's own user comes from the panel), and the
# adapters lose the template's MAC addresses (hw-id), or clones' adapters would come up as new ones.
# Then cloud-init forgets the build, so it runs on each machine's first boot, and the SSH host keys go
# (VyOS's SSH service makes new ones).

if [ "$1" != --yes ]; then
	echo "This locks the vyos user and powers the VM off: run it with --yes." >&2
	exit 1
fi
source /opt/vyatta/etc/functions/script-template

echo "==> Configuration: lock vyos, untie the adapters"
hash=$(openssl passwd -6 "$(head -c 32 /dev/urandom | base64)")
configure
set system login user vyos authentication encrypted-password "$hash"
delete system login user vyos authentication plaintext-password
delete interfaces ethernet eth0 hw-id
delete interfaces ethernet eth1 hw-id
commit
save
exit

echo "==> cloud-init, SSH host keys, traces"
sudo cloud-init clean --logs
sudo rm -f /etc/ssh/ssh_host_*
sudo rm -rf /tmp/vyos
rm -f ~/.bash_history

echo "==> Powering off"
sudo poweroff
