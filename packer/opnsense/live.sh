#!/bin/sh
# Run by opnsense.pkr.hcl's boot_command in the DVD's live system, from the build's CD (mounted at
# /tmp/lab), around OPNsense's own installer:
#
#   sh /tmp/lab/live.sh before   # the lab configuration (config.xml, from this CD) for the installer to copy
#   sh /tmp/lab/live.sh after    # on the installed disk: that configuration again, and a one-time boot
#                                # hook that adds VMware Tools (os-vmware)
#
# The live system runs with its network adapters switched off (boot_command sets hint.vmx.N.disabled
# at the loader): its default configuration would make one of them LAN, with a DHCP server, on the
# shared lab network. The installed system boots with the lab configuration instead (DHCP clients
# only), and fetches VMware Tools from OPNsense's package mirror itself; with it, Packer finds its
# address.
set -eu

here=$(dirname "$0")
case ${1:-} in
before)
	# The safety net: with an adapter here, the loader step was missed and the default configuration
	# could be serving DHCP on the lab network. Stop at once.
	if ifconfig -l | tr ' ' '\n' | grep -q '^vmx'; then
		echo "live.sh: the live system has network adapters (the loader step was missed): powering off." >&2
		shutdown -p now
		exit 1
	fi
	cp "$here/config.xml" /conf/config.xml
	echo "live.sh: the lab configuration is in place; now opnsense-installer."
	;;
after)
	# The installer's UFS root (Install (UFS)), by its GPT label.
	mkdir -p /tmp/target
	mount /dev/gpt/rootfs /tmp/target
	cp "$here/config.xml" /tmp/target/conf/config.xml
	hook=/tmp/target/usr/local/etc/rc.syshook.d/start/00-lab-build-vmware
	mkdir -p "$(dirname "$hook")"
	cat >"$hook" <<'EOF'
#!/bin/sh
# The template build only (packer/opnsense/live.sh): VMware Tools, once, then this hook goes.
for _ in 1 2 3 4 5 6 7 8 9 10; do
	pkg install -y os-vmware && break
	sleep 15
done
/usr/local/etc/rc.d/vmware-guestd onestart 2>/dev/null || service vmware-guestd onestart 2>/dev/null || true
rm -f "$0"
EOF
	chmod 755 "$hook"
	umount /tmp/target
	echo "live.sh: installed system ready; rebooting into it."
	reboot
	;;
*)
	echo "usage: live.sh before|after" >&2
	exit 2
	;;
esac
