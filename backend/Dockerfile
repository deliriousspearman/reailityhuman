# One image for the API, the workers and the builder; compose.yaml picks the command.
FROM python:3.12-slim

# The builder's tools (app/builds.py runs packer/build.sh): Packer and its vSphere plugin, as the offline
# install's tools image has them (deploy/install/Dockerfile), xorriso for the builds' CDs, ssh-keygen
# for their throwaway keys, curl for fetch-legacy.sh.
ARG PACKER_VERSION=1.16.1
ARG VSPHERE_PLUGIN_VERSION=2.5.0
ENV PACKER_PLUGIN_PATH=/opt/packer-plugins CHECKPOINT_DISABLE=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl openssh-client unzip xorriso \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/packer.zip "https://releases.hashicorp.com/packer/${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_amd64.zip" \
    && unzip -q /tmp/packer.zip -d /usr/local/bin && rm /tmp/packer.zip \
    && packer plugins install github.com/hashicorp/vsphere "v${VSPHERE_PLUGIN_VERSION}" \
    && chmod -R a+rX /opt/packer-plugins

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app
WORKDIR /app

# Dependencies first (cached until pyproject.toml changes). The app itself runs from /app, not
# site-packages, so templates.yaml and the Alembic scripts sit next to it.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && pip uninstall -y lab-deploy && rm -rf app build *.egg-info
COPY . .
RUN useradd --system --no-create-home labdeploy
# Packet captures (app/capture.py): the panel's SSH key for the capture appliance and the .pcap files,
# in a named volume (compose.yaml), which takes this folder's owner when it's first made.
RUN mkdir -m 750 /capture && chown labdeploy: /capture
USER labdeploy

EXPOSE 8000
# Migrate, then serve. The worker overrides this with its own command.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.api:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
