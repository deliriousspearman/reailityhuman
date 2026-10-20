# The offline install's tools image (lab-deploy-tools): everything the template builds and the
# install's checks run with, so the panel's server needs only Docker. deploy/bundle.sh builds it
# online and saves it into the bundle; deploy/install.sh loads it and runs the install's steps in it,
# on the host's network (the builds' VMs fetch from Packer's web server and the installer's), with the
# host's Docker socket (it starts the panel with docker compose).
FROM debian:13-slim

ARG PACKER_VERSION=1.16.1
ARG VSPHERE_PLUGIN_VERSION=2.5.0
ARG GOVC_VERSION=0.55.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates curl docker-cli docker-compose git jq openssh-client python3 python3-venv qemu-utils rsync unzip xorriso \
    && rm -rf /var/lib/apt/lists/*

# Packer and its vSphere plugin, installed where Packer looks (packer init then finds it, offline).
RUN curl -fsSL -o /tmp/packer.zip "https://releases.hashicorp.com/packer/${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_amd64.zip" \
    && unzip -q /tmp/packer.zip -d /usr/local/bin && rm /tmp/packer.zip \
    && CHECKPOINT_DISABLE=1 packer plugins install github.com/hashicorp/vsphere "v${VSPHERE_PLUGIN_VERSION}"

RUN curl -fsSL "https://github.com/vmware/govmomi/releases/download/v${GOVC_VERSION}/govc_Linux_x86_64.tar.gz" \
    | tar -xz -C /usr/local/bin govc

# The install's own Python (pyVmomi for vCenter, PyYAML for the catalogue).
RUN python3 -m venv /opt/labinstall && /opt/labinstall/bin/pip install --no-cache-dir pyvmomi==9.1.1.0 pyyaml==6.0.3
ENV PATH=/opt/labinstall/bin:$PATH CHECKPOINT_DISABLE=1 PYTHONUNBUFFERED=1

WORKDIR /srv/lab-deploy/src
