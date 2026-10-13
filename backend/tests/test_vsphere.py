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
            vc.clone("Labs/Templates/nope", "x-1", 1, 1, {})
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
    assert "- sudo" in data
    assert "- wheel" in cloudinit.userdata("rocky01", "labuser", "pw", None, admin_group="wheel")


def test_clone_onto_distributed_port_group(monkeypatch):
    from pyVmomi import vim

    from app.config import settings

    monkeypatch.setattr(settings(), "vcenter_network", "DC0_DVPG0")
    with connect() as vc:
        vm = vc.clone(TEMPLATE, "dvs01-test", 1, 1, {})
        devices = vc.props(vm, "config.hardware.device")["config.hardware.device"]
        nic = next(d for d in devices if isinstance(d, vim.vm.device.VirtualEthernetCard))
        assert isinstance(nic.backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)


def test_missing_privilege_is_named():
    from pyVmomi import vim

    from app.vsphere import describe

    fault = vim.fault.NoPermission(
        privilegeId="VirtualMachine.Interact.DeviceConnection",
        missingPrivileges=[vim.fault.NoPermission.EntityPrivileges(privilegeIds=["VirtualMachine.Interact.DeviceConnection"])],
    )
    text = describe(fault)
    assert "missing the privilege VirtualMachine.Interact.DeviceConnection" in text
    assert "setup_vcenter.py" in text


def test_nic_left_alone_when_already_on_the_port_group():
    with connect() as vc:
        tpl = vc.template(TEMPLATE)
        changes = vc._nic_change(tpl)
        # vcsim's VMs are on "VM Network", the configured port group. At most it's set to connect at
        # power on; never "connected" now, which needs the Device connection privilege.
        for change in changes:
            assert change.device.connectable.startConnected is True
            assert not change.device.connectable.connected


def test_a_task_that_never_finishes_times_out():
    from types import SimpleNamespace

    from pyVmomi import vim

    from app.vsphere import wait

    cancelled = []
    task = SimpleNamespace(info=SimpleNamespace(state=vim.TaskInfo.State.running), CancelTask=lambda: cancelled.append(True))
    with pytest.raises(VSphereError, match="Clone didn't finish"):
        wait(task, "Clone", timeout=0)
    assert cancelled


def test_faults_without_a_message_are_named():
    from pyVmomi import vim

    from app.vsphere import describe

    assert describe(vim.fault.InvalidState()) == "InvalidState"
