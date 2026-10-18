<#
.SYNOPSIS
Removes a prepared Windows VM's identity and generalizes it with sysprep, then shuts it down.

.DESCRIPTION
The Windows counterpart of clean.sh. Run it on the VM after prepare.ps1, in an elevated Windows
PowerShell. It:
  - clears what Cloudbase-Init recorded on this VM, so it runs afresh on each clone;
  - deletes the OpenSSH host keys (each clone makes its own), administrators' authorized keys (so a
    key used while building doesn't open every clone), and the panel's folder, if left from a test;
  - runs sysprep with Cloudbase-Init's Unattend.xml (generalize, then OOBE on next boot) and shuts
    the VM down.
Each clone then gets a new SID, its own name from the panel, and the panel's first-boot script.
The built-in Administrator account is disabled on each clone by that script, so the password you
used here doesn't open them.

Sysprep can't be undone: afterwards, only snapshot the VM and make it a template. Without -Yes it
only says what it would do.

.PARAMETER Yes
Really do it.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File clean.ps1 -Yes
#>
[CmdletBinding()]
param([switch]$Yes)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$CloudbaseDir = Join-Path $env:ProgramFiles 'Cloudbase Solutions\Cloudbase-Init'
$Unattend = Join-Path $CloudbaseDir 'conf\Unattend.xml'
$Sysprep = Join-Path $env:SystemRoot 'System32\Sysprep\sysprep.exe'

function Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this in an elevated PowerShell (Run as administrator).'
}
if (-not (Test-Path (Join-Path $CloudbaseDir 'conf\cloudbase-init.conf'))) {
    throw 'Cloudbase-Init is not set up: run prepare.ps1 first.'
}
if (-not (Test-Path $Unattend)) {
    throw "Missing $Unattend, which sysprep needs. Reinstall Cloudbase-Init, then re-run prepare.ps1."
}

$plan = @(
    "Clear Cloudbase-Init's records and logs",
    "Delete the OpenSSH host keys, administrators' authorized keys and C:\ProgramData\lab-deploy",
    "Remove apps installed for one user but not provisioned for all (they stop sysprep)",
    "Run sysprep /generalize /oobe /shutdown with $Unattend"
)
if (-not $Yes) {
    Write-Host 'Would:'
    $plan | ForEach-Object { Write-Host "  - $_" }
    Write-Host 'Run with -Yes to do it. The VM shuts down at the end; then snapshot it as "clean".'
    return
}

Step "Clearing Cloudbase-Init's records"
Stop-Service -Name cloudbase-init -ErrorAction SilentlyContinue
# It notes which plugins have run under a key per instance; a clone must start with none.
$records = 'HKLM:\SOFTWARE\Cloudbase Solutions\Cloudbase-Init'
if (Test-Path $records) {
    Get-ChildItem -Path $records | Remove-Item -Recurse -Force
}
Get-ChildItem -Path (Join-Path $CloudbaseDir 'log') -File -ErrorAction SilentlyContinue | Remove-Item -Force

Step "Deleting OpenSSH host keys, administrators' authorized keys and the panel folder"
Stop-Service -Name sshd -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $env:ProgramData 'ssh') -Filter 'ssh_host_*' -ErrorAction SilentlyContinue | Remove-Item -Force
# Keys any administrator could sign in with, e.g. one added while building. Each clone gets only the
# key given when it's deployed.
Remove-Item -Path (Join-Path $env:ProgramData 'ssh\administrators_authorized_keys') -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $env:ProgramData 'lab-deploy') -Recurse -Force -ErrorAction SilentlyContinue

Step 'Removing apps installed for one user only'
# Sysprep won't generalize while an app package is installed for a user but not provisioned for
# all (0x80073cf2): e.g. Microsoft Edge updating itself during the build on Windows Server 2022. Such
# packages go; Windows' own provisioned apps stay.
# (An array either way: Windows Server 2019 has no provisioned packages, and strict mode refuses
# .DisplayName on nothing.)
$provisioned = @(Get-AppxProvisionedPackage -Online | ForEach-Object { $_.DisplayName })
Get-AppxPackage -AllUsers |
    Where-Object { $_.Name -notin $provisioned -and -not $_.IsFramework -and -not $_.NonRemovable } |
    ForEach-Object {
        Write-Host "  $($_.PackageFullName)"
        Remove-AppxPackage -Package $_.PackageFullName -AllUsers -ErrorAction Continue
    }

Step 'Running sysprep: the VM shuts down when it has finished'
& $Sysprep /generalize /oobe /shutdown "/unattend:$Unattend"
# sysprep returns at once and works in the background. If the VM is still on after a few minutes,
# C:\Windows\System32\Sysprep\Panther\setuperr.log says why.
