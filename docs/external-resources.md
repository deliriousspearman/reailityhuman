# External resources

Everything the lab downloads from outside, apart from:
- **the installer ISOs:** listed, with their links and checksums, in
  [`scripts/isos/isos.txt`](../scripts/isos/isos.txt);
- **packages from each OS's own repositories** (Ubuntu, Debian, Kali, Parrot, Rocky, AlmaLinux, CentOS
  Stream, Fedora, CachyOS), which the builds install with apt, dnf or pacman.

Use it to see what needs internet, to mirror things for an
[offline install](offline-install.md), or to check for new versions. Each section names the file
that pins the version: change it there. Most downloads are checked against a pinned SHA-256 or the
publisher's checksum or signature.

## Container images (the Docker extras)

Not baked into templates: each goes on an ISO of its own in the datastore's ISO folder
(`lab-image-<extra>-<tag>.iso`), made by `scripts/isos/fetch-images.sh`, and attached at deploy. The
images are the `dockerImage:` lines in [`backend/extras.yaml`](../backend/extras.yaml);
`fetch-images.sh --list` shows them. For an [offline install](offline-install.md), `deploy/bundle.sh`
makes them all into the bundle, and the install uploads them.

| Extra | Image | From |
|---|---|---|
| Juice Shop | `bkimminich/juice-shop:v20.3.0` | [Docker Hub](https://hub.docker.com/r/bkimminich/juice-shop) |
| DVWA | `vulnerables/web-dvwa:latest` (digest pinned in `fetch-images.sh`) | [Docker Hub](https://hub.docker.com/r/vulnerables/web-dvwa) |
| Uptime Kuma | `louislam/uptime-kuma:2.5.6` | [Docker Hub](https://hub.docker.com/r/louislam/uptime-kuma) |
| Node Exporter | `prom/node-exporter:v1.12.1` | [Docker Hub](https://hub.docker.com/r/prom/node-exporter) |
| Prometheus | `prom/prometheus:v3.15.1` | [Docker Hub](https://hub.docker.com/r/prom/prometheus) |
| Grafana | `grafana/grafana:13.2.4` | [Docker Hub](https://hub.docker.com/r/grafana/grafana) |
| Vaultwarden | `vaultwarden/server:1.37.4-alpine` | [Docker Hub](https://hub.docker.com/r/vaultwarden/server) |
| Gitea | `gitea/gitea:28.1.0` | [Docker Hub](https://hub.docker.com/r/gitea/gitea) |
| GitLab CE | `gitlab/gitlab-ce:19.5.1-ce.0` | [Docker Hub](https://hub.docker.com/r/gitlab/gitlab-ce) |
| Redis | `redis:8.10.3` | [Docker Hub](https://hub.docker.com/_/redis) |
| MongoDB | `mongo:9.0.4` | [Docker Hub](https://hub.docker.com/_/mongo) |
| Apache Tomcat | `tomcat:11.0.27-jre25-temurin` | [Docker Hub](https://hub.docker.com/_/tomcat) |
| Elastic Stack (ELK) | `elasticsearch:9.5.5`, `kibana:9.5.5`, `logstash:9.5.5` | Docker Hub ([Elasticsearch](https://hub.docker.com/_/elasticsearch), [Kibana](https://hub.docker.com/_/kibana), [Logstash](https://hub.docker.com/_/logstash)) |
| Graylog | `graylog/graylog:7.2.1`, `opensearchproject/opensearch:2.19.7`, `mongo:7.0.45` | Docker Hub ([Graylog](https://hub.docker.com/r/graylog/graylog), [OpenSearch](https://hub.docker.com/r/opensearchproject/opensearch), [MongoDB](https://hub.docker.com/_/mongo)) |
| Jenkins | `lab-deploy/jenkins:2.580.2`, built from `jenkins/jenkins:2.580.2-lts-jdk21` | [Docker Hub](https://hub.docker.com/r/jenkins/jenkins), plus plugins from the [Jenkins update site](https://updates.jenkins.io/): configuration-as-code, workflow-aggregator, job-dsl, git, pipeline-stage-view |

Two extras install files rather than images, from media ISOs (`lab-media-<extra>-<version>.iso`) that
`fetch-images.sh` also makes. Their versions are pinned in `fetch-images.sh`:

| Extra | What | From |
|---|---|---|
| k3s | k3s v1.36.5+k3s1, its offline images and install script; `nginx:1.30.6-alpine` and `busybox:1.37.0` for the example workloads | <https://github.com/k3s-io/k3s/releases> (checked against `sha256sum-amd64.txt`; `install.sh` pinned by SHA-256), Docker Hub |
| Send event logs to ELK (Windows) | Winlogbeat 9.5.5 | <https://artifacts.elastic.co/downloads/beats/winlogbeat/> (checked against its `.sha512`) |

## Linux template builds

Downloaded by [`scripts/template/prepare.sh`](../scripts/template/prepare.sh) while a template is
built. Offline, [`scripts/isos/fetch-media.sh`](../scripts/isos/fetch-media.sh) gathers them into
the media folder instead.

| What | For | Link |
|---|---|---|
| WordPress (latest) | WordPress extra | <https://wordpress.org/latest.tar.gz> (checked against its `.sha1`) |
| WP-CLI | WordPress extra | <https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar> (`.sha512`) |
| Nextcloud (latest) | Nextcloud extra | <https://download.nextcloud.com/server/releases/latest.tar.bz2> (`.sha256`) |
| Nextcloud snap | Nextcloud (snap) extra | The [Snap Store](https://snapcraft.io/nextcloud), `snap install nextcloud`; not available offline |
| Chinook 1.4.5 | The databases' example data | <https://github.com/lerocha/chinook-database/releases/tag/v1.4.5> (pinned SHA-256) |
| MinIO and its client (`RELEASE.2025-04-22T22-12-26Z`, `mc` `RELEASE.2025-04-16T18-13-26Z`) | MinIO extra, built from source by [`build-minio.sh`](../scripts/template/build-minio.sh) | <https://github.com/minio/minio>, <https://github.com/minio/mc> |
| Go 1.24.13 | Building MinIO | <https://go.dev/dl/> |
| Python 3.8 to 3.15 | Python extra | [python-build-standalone](https://github.com/astral-sh/python-build-standalone/releases) (versions and SHA-256s in `PYTHON_BUILDS`) |
| Python 2.7.18, and OpenSSL 1.1.1w to build it with | Python extra | <https://www.python.org/ftp/python/2.7.18/>, <https://github.com/openssl/openssl/releases/tag/OpenSSL_1_1_1w> |
| iRedMail 1.8.8, and its extra files | iRedMail extra | <https://github.com/iredmail/iRedMail/releases/tag/1.8.8>, <https://dl.iredmail.org/yum/misc/> |
| Wazuh 4.14 installer, and the agent 4.14.9 | Wazuh server and agent extras | <https://packages.wazuh.com/4.14/wazuh-install.sh>, <https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/> |
| Zabbix 7.0 LTS repository | Zabbix server and agent extras | <https://repo.zabbix.com> (its key is checked) |
| Ondřej Surý's PHP repository | PHP 5.6 to 8.5 for the Apache extras (Ubuntu) | <https://launchpad.net/~ondrej/+archive/ubuntu/php> |
| Zimbra 8.8.15 and its repository | The Zimbra template | <https://files.zimbra.com/downloads/8.8.15_GA/>, <https://repo.zimbra.com> |

`prepare.sh` also asks the Snap Store (<https://api.snapcraft.io>) whether it can be reached, to
decide whether to install the Nextcloud snap.

## Windows template builds

| What | For | Pinned in | Link |
|---|---|---|---|
| Cloudbase-Init 1.1.9 | Every Windows template's first boot | `packer/windows-server/provision.ps1` | <https://github.com/cloudbase/cloudbase-init/releases/tag/1.1.9> |
| Office Deployment Tool | Outlook | `provision.ps1` | <https://officecdn.microsoft.com/pr/wsus/setup.exe> (Office itself is gathered on a PC: [build-templates.md](build-templates.md)) |
| Visual C++ 2012 and 2013, IIS URL Rewrite | Exchange's prerequisites | `scripts/template/prepare.ps1` | download.microsoft.com and download.visualstudio.microsoft.com (links and SHA-256s in `prepare.ps1`) |
| Chinook for SQL Server | SQL Server's example data | `prepare.ps1` | <https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_SqlServer.sql> |
| Universal C Runtime (KB2999226), .NET 4.8, WMF 5.1 (KB3191564) | Windows Server 2012 R2 | `packer/windows-server/legacy.ps1` | download.microsoft.com and download.visualstudio.microsoft.com (links and SHA-256s in `legacy.ps1`); gathered by `fetch-legacy.sh` |
| Win32-OpenSSH 9.8.3.0 | Windows Server 2016 and 2012 R2 | `legacy.ps1` | <https://github.com/PowerShell/Win32-OpenSSH/releases> |

SQL Server, Exchange and the Windows installers themselves are ISOs, in `isos.txt`.

## Appliances and complete images

Templates made from a vendor's image rather than an installer ISO.

| Template | Image | Imported by | Link |
|---|---|---|---|
| Parrot Security 7.4 | Security OVA | `packer/parrot/import-base.sh` | <https://deb.parrot.sh/parrot/iso/> (checked against `signed-hashes.txt`) |
| Metasploitable 2 | VM image | `packer/metasploitable/import-ms2.sh` | <https://sourceforge.net/projects/metasploitable/files/Metasploitable2/> |
| Metasploitable 2's VMware Tools | Tools for its old glibc | `import-ms2.sh` | <https://packages.vmware.com/tools/frozen/linux/linuxPreGlibc25.iso> |
| Metasploitable 3 (Linux and Windows) | Rapid7's Vagrant boxes | `import-ms3.sh`, `import-ms3-win.sh` | <https://portal.cloud.hashicorp.com/vagrant/discover/rapid7> |
| MikroTik CHR 7.24.5 and 6.49.23 | VMDK | `packer/mikrotik/import-chr.sh` | <https://download.mikrotik.com/routeros/> (with its `.sha256`) |
| VyOS (rolling) | Built into an ISO | `packer/vyos/build-iso.sh` | <https://github.com/vyos/vyos-build> and its build image `vyos/vyos-build:rolling` (Docker Hub) |

## Other package repositories

Repositories outside the OS's defaults, or archives of old releases' repositories.

| Repository | Used by | Link |
|---|---|---|
| Proxmox VE (no-subscription), and its key | The Proxmox templates | <http://download.proxmox.com/debian/>, key from <https://enterprise.proxmox.com/debian/> |
| CentOS Vault (CentOS 6, 7.9) | CentOS 6 and 7, and XCP-ng's build | <http://vault.centos.org/> |
| EPEL 6 archive | CentOS 6 | <http://archives.fedoraproject.org/pub/archive/epel/6/> |
| OPNsense 26.7 packages | Offline OPNsense builds (`fetch-media.sh`) | <https://pkg.opnsense.org/FreeBSD:15:amd64/26.7/latest> |
| pfSense CE 2.7.2 packages | Offline pfSense builds (`fetch-media.sh`) | <https://pkg00-atx.netgate.com/pfSense_v2_7_2_amd64-pfSense_v2_7_2> |
| Docker CE | The panel's server (`deploy/setup-server.sh`, `deploy/bundle.sh`) | <https://download.docker.com/linux/ubuntu> |

## The panel and its tooling

| What | Version | Where it's pinned | Link |
|---|---|---|---|
| Packer | 1.16.1 | `backend/Dockerfile`, `deploy/install/Dockerfile`, `fetch-media.sh` | <https://releases.hashicorp.com/packer/> |
| Packer's vSphere plugin | 2.5.0 | the same files | <https://github.com/hashicorp/packer-plugin-vsphere/releases> |
| govc | 0.55.2 (binary and `vmware/govc` image) | `deploy/install/Dockerfile`, `fetch.sh`, `fetch-images.sh` | <https://github.com/vmware/govmomi/releases> |
| The panel's containers | `python:3.12-slim`, `postgres:16-alpine`, `caddy:2` | `backend/Dockerfile`, `deploy/compose.yaml` | Docker Hub |
| The offline installer's container | `debian:13-slim` | `deploy/install/Dockerfile` | Docker Hub |
| Python packages (the backend) | in `backend/pyproject.toml` | `backend/pyproject.toml` | <https://pypi.org> |
| npm packages (the frontend) | in `frontend/package-lock.json` | `frontend/package.json` | <https://registry.npmjs.org> |
| CI and test images | `node:22-alpine`, `koalaman/shellcheck-alpine:v0.10.0`, `mcr.microsoft.com/powershell:7.4-ubuntu-22.04`, `alpine:3`, `vmware/vcsim:v0.53.0` | `.gitlab-ci.yml`, `backend/compose.test.yaml` | Docker Hub, Microsoft's registry |
