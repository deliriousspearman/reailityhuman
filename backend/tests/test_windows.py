"""Windows machines: the Cloudbase-Init data, and the worker waiting for setup (with the guest's status
file faked: vcsim VMs have no guest). vcsim's VM stands in for a Windows template."""

import base64
import re
from dataclasses import replace

import pytest
import yaml
from fastapi.testclient import TestClient

from app import catalogue, cloudinit, extras
from app.api import app
from app.vsphere import VCenter, connect

from .conftest import TEMPLATE, run_queued

client = TestClient(app)
KEY = ("windows-server", "2025")


@pytest.fixture
def windows(monkeypatch):
    """A Windows Server 2025 template, offering IIS."""
    ubuntu = catalogue.catalogue()[("ubuntu", "26.04")]
    tpl = replace(
        ubuntu, template=KEY[0], version=KEY[1], vsphere=TEMPLATE, username="labadmin", family="windows",
        admin_group="Administrators", extras=("iis",),
    )  # fmt: skip
    monkeypatch.setitem(catalogue.catalogue(), KEY, tpl)


@pytest.fixture
def guest(monkeypatch):
    """What the machine's status file says; None: not written yet."""
    state = {"status": None, "reads": []}

    def read(self, vm, username, password, path):
        state["reads"].append((username, path))
        return state["status"]

    monkeypatch.setattr(VCenter, "read_guest_file", read)
    return state


def deploy(name="win01", **extra):
    body = {"template": KEY[0], "version": KEY[1], "owner": "jo", "name": name, "hours": 2, **extra}
    return client.post("/api/machines", json=body)


def decoded(script: str) -> list[str]:
    """The values a script carries base64-encoded (extras.ps_string)."""
    return [base64.b64decode(b).decode() for b in re.findall(r"FromBase64String\('([^']*)'\)", script)]


# The data ---------------------------------------------------------------------------------------------


def test_metadata_names_the_instance_and_computer():
    assert yaml.safe_load(cloudinit.windows_metadata("m-1234", "win01")) == {"instance-id": "m-1234", "local-hostname": "win01"}


def test_userdata_is_a_powershell_script_carrying_values_encoded():
    password = "It's \"quoted\" `x` ‘smart’ $(Get-Date)"
    chosen = [{"id": "iis", "options": {}}]
    script = cloudinit.windows_userdata("labadmin", password, "ssh-ed25519 AAAA test", chosen, "win01")
    assert script.startswith("#ps1_sysnative\r\n")
    assert password not in script and "ssh-ed25519" not in script  # only base64 of them
    values = decoded(script)
    assert password in values and "ssh-ed25519 AAAA test" in values and "labadmin" in values
    assert "S-1-5-32-544" in script  # Administrators, by SID
    # As commands' arguments, encoded values must be in brackets, or PowerShell takes them as text.
    assert "ConvertTo-SecureString ([Text.Encoding]::UTF8.GetString(" in script
    assert "Add-Content -Path $keys -Value ([Text.Encoding]::UTF8.GetString(" in script
    assert "administrators_authorized_keys" in script
    assert "-500' -and $_.Name -ne $user } | Disable-LocalUser" in script  # the built-in Administrator
    assert "Start-Service -Name sshd" in script
    # The extras: the runner and IIS's script written, then run; failures still write the status file.
    files = {v.splitlines()[0]: v for v in values if v.startswith("#")}
    assert any("applies the extras" in line for line in files)
    iis = next(v for v in values if v.startswith("# IIS"))
    assert "Install-WindowsFeature" in iis and "$hostname = " in iis and "win01" in decoded(iis)
    assert f"& '{extras.WINDOWS_DIR}\\extras\\run.ps1' -Ids @('iis')" in script
    assert "failed setup" in script and extras.WINDOWS_STATUS_FILE in script


def test_userdata_without_key_or_extras_still_writes_the_status_file():
    script = cloudinit.windows_userdata("labadmin", "Pass-word1", None, [], "win01")
    assert "administrators_authorized_keys" not in script
    assert "run.ps1' -Ids @()" in script  # an empty status file: set up, nothing to install


def test_guestinfo_keys():
    keys = cloudinit.windows_guestinfo("m-1", "win01", "labadmin", "Pass-word1", None, [])
    assert set(keys) == {"guestinfo.metadata", "guestinfo.metadata.encoding", "guestinfo.userdata", "guestinfo.userdata.encoding"}
    assert base64.b64decode(keys["guestinfo.userdata"]).decode().startswith("#ps1_sysnative")


def test_windows_extras_scripts():
    [c] = extras.resolve(("iis",), [{"id": "iis"}], "win01")
    script = extras.script(extras.find("iis"), "windows", "win01", c["options"])
    assert script.startswith("# IIS, written by the lab panel.\r\n$ErrorActionPreference = 'Stop'\r\n")
    assert "\n" not in script.replace("\r\n", "")  # Windows line endings throughout
    assert extras.status_file("windows") == r"C:\ProgramData\lab-deploy\extras.status"
    assert extras.log_file("windows", "iis") == r"C:\ProgramData\lab-deploy\logs\iis.log"


# Passwords --------------------------------------------------------------------------------------------


def test_generated_passwords_suit_windows():
    for _ in range(200):
        assert cloudinit.windows_password_problem(cloudinit.generate_password(16), "labadmin") is None


@pytest.mark.parametrize(
    "password, ok",
    [("Correct-horse", True), ("correcthorse9", False), ("CORRECT horse", True), ("labadmin-X9", False), ("Pass-word1", True)],
)
def test_windows_password_rules(password, ok):
    assert (cloudinit.windows_password_problem(password, "labadmin") is None) == ok


def test_deploy_refuses_passwords_windows_would(windows):
    r = deploy(password="alllowercase1")
    assert r.status_code == 422 and "three of" in r.json()["detail"]


# Through the API and the worker -------------------------------------------------------------------------


def test_deploy_waits_for_setup_then_forgets_the_password(queued, windows, guest):
    guest["status"] = "ok iis\n"
    r = deploy(extras=[{"id": "iis"}], password="Correct-horse9")
    assert r.status_code == 201, r.text
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running", m["log"]
    texts = [line["text"] for line in m["log"]]
    assert "Windows is setting up, with IIS. This takes a few minutes…" in texts
    assert "IIS is ready" in texts
    assert texts[-1] == "Ready. Sign in as labadmin."
    assert guest["reads"] == [("labadmin", extras.WINDOWS_STATUS_FILE)]
    with connect() as vc:
        config = vc.props(vc.require_vm(m["vmName"]), "config.extraConfig")["config.extraConfig"]
    values = {o.key: o.value for o in config}
    assert values.get("guestinfo.userdata", "") == ""
    assert values["guestinfo.metadata"]  # the instance and name stay
    assert client.get("/api/config").json()["templates"][-1]["family"] == "windows"


def test_windows_waits_even_without_extras(queued, windows, guest):
    guest["status"] = ""
    r = deploy()
    run_queued(queued)
    assert client.get(f"/api/machines/{r.json()['id']}").json()["state"] == "running"
    assert len(guest["reads"]) == 1


def userdata_in_vcenter(vm_name: str) -> str:
    with connect() as vc:
        config = vc.props(vc.require_vm(vm_name), "config.extraConfig")["config.extraConfig"]
    return {o.key: o.value for o in config}.get("guestinfo.userdata", "")


def test_failed_setup_fails_the_deploy(queued, windows, guest):
    guest["status"] = "failed setup The password does not meet the password policy requirements.\n"
    r = deploy()
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert "Setting up the machine failed: The password does not meet" in m["log"][-1]["text"]
    assert userdata_in_vcenter(m["vmName"]) == ""  # the password is cleared all the same


def test_timed_out_setup_still_clears_the_password(queued, windows, guest, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "windows_setup_timeout_seconds", 0)
    r = deploy()
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error" and "didn't finish setting up" in m["log"][-1]["text"]
    assert userdata_in_vcenter(m["vmName"]) == ""


def test_failed_windows_extra_names_its_log(queued, windows, guest):
    guest["status"] = "failed iis Install-WindowsFeature : The request to add or remove features failed.\n"
    r = deploy(extras=[{"id": "iis"}])
    run_queued(queued)
    text = client.get(f"/api/machines/{r.json()['id']}").json()["log"][-1]["text"]
    assert "iis didn't install" in text and r"C:\ProgramData\lab-deploy\logs\iis.log" in text


def test_timeout_says_when_the_user_cant_sign_in(queued, windows, guest, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "windows_setup_timeout_seconds", 0)
    monkeypatch.setattr(VCenter, "guest_login_ok", lambda self, vm, user, password: False)
    r = deploy()
    run_queued(queued)
    text = client.get(f"/api/machines/{r.json()['id']}").json()["log"][-1]["text"]
    assert "labadmin can't sign in, so creating the user probably failed" in text


def test_no_ssh_where_the_template_doesnt_offer_it():
    script = cloudinit.windows_userdata("labadmin", "Pass-word1", "ssh-ed25519 AAAA test", [], "win01", ssh=False)
    assert "sshd" not in script and "administrators_authorized_keys" not in script
    assert "Start-Service -Name sshd" in cloudinit.windows_userdata("labadmin", "Pass-word1", None, [], "win01")


def test_deploy_follows_the_templates_access(queued, windows, guest, monkeypatch):
    seen = {}
    real = cloudinit.windows_guestinfo

    def spy(*args):
        seen["ssh"] = args[-1]
        return real(*args)

    monkeypatch.setattr(cloudinit, "windows_guestinfo", spy)
    tpl = catalogue.catalogue()[KEY]
    monkeypatch.setitem(catalogue.catalogue(), KEY, replace(tpl, access=("rdp", "console")))
    guest["status"] = ""
    deploy()
    run_queued(queued)
    assert seen["ssh"] is False
