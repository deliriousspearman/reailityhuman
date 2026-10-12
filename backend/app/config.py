"""Settings, read from the environment (lab-deploy.env on the server; see deploy/lab-deploy.env.example)."""

from functools import lru_cache
from pathlib import Path

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
    # Optional resource pool inside the cluster, e.g. "ProLabs". Default: the cluster's root pool.
    vcenter_resource_pool: str = ""
    vcenter_datastore: str = ""
    # VM folder for machines, under the datacenter's VM folder.
    vcenter_folder: str = "ProLabs/Machines"
    # Port group machines join (the LAN, with DHCP).
    vcenter_network: str = ""

    # Machines that may exist at once, and how many of those may be kept permanently.
    max_machines: int = 10
    max_permanent: int = 3
    # How long an expired machine is kept (powered off) before it's deleted.
    grace_minutes: int = 24 * 60
    # How long a deploy waits for the machine to report an IP address.
    ip_timeout_seconds: int = 300
    password_length: int = 16

    catalogue_path: Path = Path(__file__).resolve().parent.parent / "templates.yaml"

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    @property
    def vcenter_configured(self) -> bool:
        return bool(self.vcenter_host and self.vcenter_user and self.vcenter_datacenter and self.vcenter_cluster)


@lru_cache
def settings() -> Settings:
    return Settings()
