"""The vSphere adapter against vcsim."""

from app import cloudinit
from app.vsphere import CLEAN, VSphereError, connect

from .conftest import TEMPLATE

import pytest


def test_clone_power_reset_destroy():
    extra = cloudinit.guestinfo("m-test", "ubuntu01", "ubuntu", "secret", None)
    with connect() as vc:
        vm = vc.clone(TEMPLATE, "ubuntu01-test", 2, 2, extra)
        assert vc.vm("ubuntu01-test") is not None
        assert not vc.powered_on(vm)
        assert vc._snapshot(vm, CLEAN) is not None
        props = vc.props(vm, "config.hardware.numCPU", "config.hardware.memoryMB", "config.extraConfig")
        assert props["config.hardware.numCPU"] == 2
        assert props["config.hardware.memoryMB"] == 2048
        keys = {o.key for o in props["config.extraConfig"]}
        assert {"guestinfo.metadata", "guestinfo.userdata"} <= keys

        vc.power_on(vm)
        assert vc.powered_on(vm)
        vc.shutdown(vm, timeout=1)
        assert not vc.powered_on(vm)
        vc.revert_to_clean(vm)
        vc.power_on(vm)
        vc.reboot(vm)
        vc.destroy(vm)
        assert vc.vm("ubuntu01-test") is None


def test_clone_needs_clean_snapshot_and_unique_name():
    with connect() as vc:
        with pytest.raises(VSphereError, match="not found"):
            vc.clone("ProLabs/Templates/nope", "x-1", 1, 1, {})
        vc.clone(TEMPLATE, "dup-1", 1, 1, {})
        with pytest.raises(VSphereError, match="already exists"):
            vc.clone(TEMPLATE, "dup-1", 1, 1, {})


def test_capacity():
    with connect() as vc:
        c = vc.capacity()
    assert c.cpu > 0 and c.memory_gb > 0 and c.disk_gb > 0


def test_cloudinit_userdata():
    data = cloudinit.userdata("ubuntu01", "ubuntu", "pw", "ssh-ed25519 AAAA test")
    assert data.startswith("#cloud-config\n")
    assert "hostname: ubuntu01" in data
    assert "ssh-ed25519 AAAA test" in data
    assert "pw" not in data.replace("passwd", "").replace("ssh_pwauth", "")  # only the hash
    assert cloudinit.hash_password("pw").startswith("$6$")
    assert len(cloudinit.generate_password(16)) == 16


def test_clone_onto_distributed_port_group(monkeypatch):
    from pyVmomi import vim

    from app.config import settings

    monkeypatch.setattr(settings(), "vcenter_network", "DC0_DVPG0")
    with connect() as vc:
        vm = vc.clone(TEMPLATE, "dvs01-test", 1, 1, {})
        devices = vc.props(vm, "config.hardware.device")["config.hardware.device"]
        nic = next(d for d in devices if isinstance(d, vim.vm.device.VirtualEthernetCard))
        assert isinstance(nic.backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
