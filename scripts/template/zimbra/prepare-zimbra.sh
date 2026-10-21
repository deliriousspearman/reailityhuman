#!/usr/bin/env bash
# Puts Zimbra Collaboration 8.8.15 (open source; the GA build, 4179, without the patches that came
# after it) into an Ubuntu 20.04 template, installed but not configured: the zimbra extra
# (backend/extras.yaml) configures it on each machine's first boot, for that machine's name and mail
# domain. prepare.sh runs it, from beside it, when the template is built with --extras=zimbra
# (packer/build.sh ubuntu -var zimbra=true …; the template's entry in deploy/install/manifest.toml has
# the whole command). On its own:
#
#   sudo bash prepare-zimbra.sh
#
# Zimbra's own packages are in its tarball; the third-party software they're built on (Zimbra's
# OpenJDK, OpenLDAP, MariaDB, Postfix, nginx… as zimbra-*-components) comes from its apt repository,
# repo.zimbra.com, which is still up. Offline: ZIMBRA_MIRROR=<URL of a mirror of
# https://repo.zimbra.com> and ZIMBRA_URL=<URL of the folder with the tarball> (the media folder's
# linux/zimbra, from scripts/isos/fetch-media.sh).
set -euo pipefail

TARBALL=zcs-8.8.15_GA_4179.UBUNTU20_64.20211118033954
SHA256=69b5803c923143015955a611109a144a09697ec9d1ee6f2df41ee561c9ab8c34
ZIMBRA_URL=${ZIMBRA_URL:-https://files.zimbra.com/downloads/8.8.15_GA}
ZIMBRA_MIRROR=${ZIMBRA_MIRROR:-https://repo.zimbra.com}
# A single server's packages. Not zimbra-dnscache: Ubuntu's own resolver has port 53.
PACKAGES="zimbra-core zimbra-ldap zimbra-logger zimbra-mta zimbra-snmp zimbra-store zimbra-apache zimbra-spell zimbra-memcached zimbra-proxy"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# shellcheck source=/dev/null
. /etc/os-release
if [[ $ID != ubuntu || $VERSION_ID != 20.04 ]]; then
	echo "This Zimbra build is for Ubuntu 20.04, not $PRETTY_NAME." >&2
	exit 1
fi
export DEBIAN_FRONTEND=noninteractive

echo "==> Zimbra's apt repository ($ZIMBRA_MIRROR)"
# Its signing key: Zimbra Packaging Services, 254F 9170 B966 D193 D6BA D300 D5CE F8BF 9BE6 ED79.
install -m 644 "$here/zimbra-archive-keyring.asc" /usr/share/keyrings/zimbra-archive-keyring.asc
cat >/etc/apt/sources.list.d/zimbra.list <<EOF
# Written by the lab panel's prepare-zimbra.sh: Zimbra's repositories, as its installer writes them.
deb [arch=amd64 signed-by=/usr/share/keyrings/zimbra-archive-keyring.asc] $ZIMBRA_MIRROR/apt/87 focal zimbra
deb [arch=amd64 signed-by=/usr/share/keyrings/zimbra-archive-keyring.asc] $ZIMBRA_MIRROR/apt/8815 focal zimbra
EOF
apt-get update -q

echo "==> Zimbra 8.8.15 GA, software only"
dir=$(mktemp -d)
curl -fsSL -o "$dir/zcs.tgz" "$ZIMBRA_URL/$TARBALL.tgz"
echo "$SHA256  $dir/zcs.tgz" | sha256sum -c --quiet
tar -xzf "$dir/zcs.tgz" -C "$dir"
rm "$dir/zcs.tgz"
# Its installer wants this machine's full name (hostname --fqdn) in /etc/hosts with a real address:
# a stand-in while it runs, in place of Ubuntu's 127.0.1.1 line for the name. (Each machine's own goes
# in when the extra configures it.)
cp /etc/hosts "$dir/hosts"
sed -i '/^127\.0\.1\.1\s/d' /etc/hosts
echo "$(hostname -I | awk '{print $1}') $(hostname).lab.example $(hostname)" >>/etc/hosts
# Its answers: these packages, from the repository set up above (not one it would write itself).
printf 'INSTALL_PACKAGES="%s"\nUSE_ZIMBRA_PACKAGE_SERVER="no"\n' "$PACKAGES" >"$dir/answers"
(cd "$dir/$TARBALL" && ./install.sh -s -x "$dir/answers" </dev/null)
cp "$dir/hosts" /etc/hosts
rm -rf "$dir"

# What a configured server would start, off until then.
systemctl disable -q zimbra 2>/dev/null || true
for pkg in $PACKAGES; do
	dpkg-query -W -f '${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || { echo "$pkg didn't install: /tmp/install.log.*" >&2; exit 1; }
done
echo "  $(dpkg-query -W -f '${Version}' zimbra-core), in $(du -sh /opt/zimbra | cut -f1)"
