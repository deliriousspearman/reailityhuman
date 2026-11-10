"""Settings, read from the environment (lab-deploy.env on the server; see deploy/lab-deploy.env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # postgresql://user:password@host/db
    database_url: str = "postgresql://labdeploy:labdeploy@localhost/labdeploy"

    # vCenter. Left empty, the API still runs but deploys fail with "vCenter isn't configured".
    vcenter_host: str = ""
    vcenter_user: str = ""
    vcenter_password: str = ""
    # Accept vCenter's self-signed certificate.
    vcenter_insecure: bool = False
    vcenter_datacenter: str = ""
    # Cluster (or standalone host) that machines run on, under the datacenter's host folder.
    vcenter_cluster: str = ""
    # Optional resource pool inside the cluster, e.g. "Labs". Default: the cluster's root pool.
    vcenter_resource_pool: str = ""
    vcenter_datastore: str = ""
    # VM folder for machines, under the datacenter's VM folder.
    vcenter_folder: str = "Labs/Machines"
    # Port group machines join (the LAN, with DHCP).
    vcenter_network: str = ""

    # Machines that may exist at once, and how many of those may be kept permanently.
    max_machines: int = 10
    max_permanent: int = 3
    # How far machines may overcommit the cluster's memory: 1.5 lets VMs be configured with 1.5x
    # the physical memory, and ESXi reclaims what they don't use (ballooning, compression).
    memory_overcommit: float = Field(default=1.0, ge=1.0)
    # Datastore space deploys never use (GB): a full datastore pauses every VM that writes to it.
    datastore_reserve_gb: int = 30
    # What a new machine writes on its own (GB), as a linked clone: logs, updates, Windows' first
    # boot. Extras that write more add their diskGB (extras.yaml).
    clone_disk_gb: int = 10
    # How long an expired machine is kept (powered off) before it's deleted.
    grace_minutes: int = 24 * 60
    # How long a deploy waits for the machine to report an IP address.
    ip_timeout_seconds: int = 300
    # How long a deploy or reset waits for the chosen extras to finish installing.
    extras_timeout_seconds: int = 600
    # How long a Windows deploy or reset waits for the machine to finish setting up (sysprep,
    # renaming and restarting, the user, then any extras).
    windows_setup_timeout_seconds: int = 1200
    # Domain for default names, e.g. a certificate's: "lab.example" makes it "ubuntu01.lab.example".
    # Empty: just the machine's name.
    machine_domain: str = ""
    # Templates withdrawn for now, e.g. "ubuntu/26.04,debian/13": not deployed or built, whatever
    # templates.yaml says (a build found broken, until it's fixed and rebuilt). Empty: none.
    blocked_templates: str = ""
    password_length: int = 16

    # Templates on demand (docs/plan.md, section 11). The templates folder, and the datastore's ISO
    # folder the builds read from.
    vcenter_template_folder: str = "Labs/Templates"
    vcenter_iso_folder: str = "ISO"
    # The builder's copy of packer/ and scripts/ (deploy.sh puts them there), and where each build's
    # whole output is kept.
    build_dir: Path = Path("/build")
    build_logs_dir: Path = Path("/build-logs")
    # The address build VMs fetch their answer files from (Packer's HTTP server): this server's on
    # the LAN. Empty: Packer's own guess.
    build_http_ip: str = ""
    # Offline: the media folder scripts/isos/fetch-media.sh makes, for the Windows builds.
    build_media_dir: str = ""
    # A build that takes longer is stopped (the slowest take about 70 minutes).
    build_timeout_minutes: int = 180

    # Packet captures (app/capture.py): the capture appliance (packer/capture), by its VM in vCenter
    # (its address is read from VMware Tools, so DHCP can give it any), or by its address. Both empty:
    # captures are off. The panel's SSH key for it, the appliance's host key (pinned on first use) and
    # the captures themselves are kept in capture_dir.
    capture_vm: str = ""
    capture_host: str = ""
    capture_dir: Path = Path("/capture")
    # The longest and largest a capture may be, how many may run at once (each person's, and in all),
    # and how long finished ones are kept.
    capture_max_seconds: int = Field(default=600, ge=10)
    capture_max_mb: int = Field(default=50, ge=1)
    capture_per_owner: int = Field(default=1, ge=1)
    capture_total: int = Field(default=3, ge=1)
    capture_keep_days: int = Field(default=1, ge=1)

    catalogue_path: Path = Path(__file__).resolve().parent.parent / "templates.yaml"

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    def template_blocked(self, template: str, version: str) -> bool:
        return f"{template}/{version}" in {t.strip() for t in self.blocked_templates.split(",") if t.strip()}

    @property
    def capture_configured(self) -> bool:
        return bool(self.capture_host or self.capture_vm)

    @property
    def vcenter_configured(self) -> bool:
        return bool(self.vcenter_host and self.vcenter_user and self.vcenter_datacenter and self.vcenter_cluster)


@lru_cache
def settings() -> Settings:
    return Settings()
