<#
.SYNOPSIS
Prepares a freshly installed Windows VM to become a template the lab panel can clone.

.DESCRIPTION
The Windows counterpart of prepare.sh. Run it on the VM in an elevated Windows PowerShell, signed in
as Administrator. It:
  - checks the Windows version and that VMware Tools is installed and running;
  - installs Cloudbase-Init from its MSI, and configures it to read each clone's data from vCenter
    (VMware guestinfo): the computer name during sysprep, then the panel's first-boot script;
  - turns on Remote Desktop (with Network Level Authentication) and its firewall rules;
  - turns on OpenSSH Server, if Windows has it, with PowerShell as its shell;
  - stops Server Manager opening at every sign-in, and never sleeps.
It's safe to re-run. Then install anything every machine should have, and run clean.ps1.

The whole process, including the vCenter steps, is in docs/setup-vsphere.md.

.PARAMETER Msi
The Cloudbase-Init 64-bit MSI (CloudbaseInitSetup_x64.msi), copied onto the VM. Not needed when
Cloudbase-Init is installed already.

.PARAMETER NoSsh
Don't set up OpenSSH Server.

.PARAMETER DryRun
Only say what it found and what it would do.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File prepare.ps1 -Msi C:\Users\Administrator\Downloads\CloudbaseInitSetup_x64.msi
#>
[CmdletBinding()]
param(
    [string]$Msi,
    [switch]$NoSsh,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$CloudbaseDir = Join-Path $env:ProgramFiles 'Cloudbase Solutions\Cloudbase-Init'
$ConfDir = Join-Path $CloudbaseDir 'conf'

function Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Note([string]$Text) { Write-Host "    $Text" }

# Checks ---------------------------------------------------------------------------------------------

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this in an elevated PowerShell (Run as administrator).'
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'Cloudbase-Init only supports 64-bit Windows.'
}
$os = Get-CimInstance Win32_OperatingSystem
# 10.0 covers Windows 10 and 11, and Server 2016 to 2025.
if ([Version]$os.Version -lt [Version]'10.0') {
    throw "$($os.Caption) is too old: the scripts support Windows 10 and Server 2016 or later."
}
$server = $os.ProductType -ne 1
$tools = Get-Service -Name VMTools -ErrorAction SilentlyContinue
if (-not $tools -or $tools.Status -ne 'Running') {
    throw 'VMware Tools must be installed and running first: in vCenter, Guest OS > Install VMware Tools.'
}
# Cloudbase-Init reads the panel's data with this; without it, clones would quietly get nothing.
$rpctool = Join-Path $env:ProgramFiles 'VMware\VMware Toolspctool.exe'
if (-not (Test-Path $rpctool)) {
    throw "VMware Tools has no $rpctool, which Cloudbase-Init needs to read each clone's data. Reinstall VMware Tools (Typical)."
}
$installed = Test-Path (Join-Path $CloudbaseDir 'Python\Scripts\cloudbase-init.exe')
if (-not $installed -and -not $Msi) {
    throw 'Cloudbase-Init is not installed: copy its MSI onto the VM and pass it with -Msi.'
}
if ($Msi -and -not (Test-Path $Msi)) {
    throw "No such file: $Msi"
}
$sshCapability = $null
if (-not $NoSsh) {
    $sshCapability = Get-WindowsCapability -Online | Where-Object { $_.Name -like 'OpenSSH.Server*' } | Select-Object -First 1
}

Step "Found $($os.Caption) ($($os.Version)), VMware Tools running"
Note "Cloudbase-Init: $(if ($installed) { 'installed' } else { "to install from $Msi" })"
if ($NoSsh) {
    Note 'OpenSSH Server: skipped (-NoSsh)'
} elseif (-not $sshCapability) {
    Note 'OpenSSH Server: not available on this Windows; machines get Remote Desktop only'
} else {
    Note "OpenSSH Server: $($sshCapability.State)"
}
if ($DryRun) {
    Note 'Dry run: nothing changed.'
    return
}

# Cloudbase-Init ---------------------------------------------------------------------------------------

if (-not $installed) {
    Step 'Installing Cloudbase-Init'
    $log = Join-Path $env:TEMP 'cloudbase-init-install.log'
    # As LocalSystem, so it can create users; no serial-port logging (VMs have no serial port).
    $arguments = @('/i', "`"$Msi`"", '/qn', '/norestart', '/l*v', "`"$log`"", 'RUN_SERVICE_AS_LOCAL_SYSTEM=1', 'LOGGINGSERIALPORTNAME=""')
    $process = Start-Process -FilePath msiexec.exe -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "The Cloudbase-Init installer failed (exit code $($process.ExitCode)); see $log"
    }
}

Step 'Configuring Cloudbase-Init for the lab panel'
# Shared by both stages. The panel's data comes from VMware guestinfo (read through VMware Tools).
$common = @"
[DEFAULT]
# Written by the lab panel's scripts/template/prepare.ps1.
bsdtar_path=$CloudbaseDir\bin\bsdtar.exe
mtools_path=$CloudbaseDir\bin\
verbose=true
debug=true
log_dir=$CloudbaseDir\log\
default_log_levels=comtypes=INFO,suds=INFO,iso8601=WARN,requests=WARN
local_scripts_path=$CloudbaseDir\LocalScripts\
metadata_services=cloudbaseinit.metadata.services.vmwareguestinfoservice.VMwareGuestInfoService
check_latest_version=false
netbios_host_name_compatibility=true
first_logon_behaviour=no
"@
# During sysprep (specialize): the computer name, which takes effect at the restart that follows.
$unattend = $common + "`r`n" + @"
log_file=cloudbase-init-unattend.log
plugins=cloudbaseinit.plugins.common.sethostname.SetHostNamePlugin,cloudbaseinit.plugins.windows.extendvolumes.ExtendVolumesPlugin
allow_reboot=false
stop_service_on_exit=false
"@
# The service, at each boot: the name again (nothing to do once set), then the panel's first-boot
# script, which it runs once per instance.
$service = $common + "`r`n" + @"
log_file=cloudbase-init.log
plugins=cloudbaseinit.plugins.common.sethostname.SetHostNamePlugin,cloudbaseinit.plugins.common.userdata.UserDataPlugin
allow_reboot=true
stop_service_on_exit=false
"@
Set-Content -Path (Join-Path $ConfDir 'cloudbase-init-unattend.conf') -Value $unattend -Encoding ascii
Set-Content -Path (Join-Path $ConfDir 'cloudbase-init.conf') -Value $service -Encoding ascii
if (-not (Test-Path (Join-Path $ConfDir 'Unattend.xml'))) {
    throw "Cloudbase-Init's Unattend.xml is missing from $ConfDir; clean.ps1 needs it for sysprep. Reinstall Cloudbase-Init."
}
Set-Service -Name cloudbase-init -StartupType Automatic

# Remote Desktop -----------------------------------------------------------------------------------------

Step 'Turning on Remote Desktop'
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
# Network Level Authentication: sign in before a session starts.
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name UserAuthentication -Value 1
# The "Remote Desktop" rule group, by its resource name: its display name depends on the language.
Enable-NetFirewallRule -Group '@FirewallAPI.dll,-28752'

# OpenSSH Server ------------------------------------------------------------------------------------------

if ($sshCapability) {
    Step 'Turning on OpenSSH Server'
    if ($sshCapability.State -ne 'Installed') {
        # Needs the Features on Demand source: Windows Update, or media on an offline network.
        Add-WindowsCapability -Online -Name $sshCapability.Name | Out-Null
    }
    Set-Service -Name sshd -StartupType Automatic
    if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
    }
    Enable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP'
    New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
    Set-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
    # Started on each clone by the panel's first-boot script, once it has its own host keys.
}

# Odds and ends -------------------------------------------------------------------------------------------

Step 'Settings for a lab machine'
if ($server) {
    # Server Manager opens at every sign-in otherwise.
    Get-ScheduledTask -TaskName ServerManager -ErrorAction SilentlyContinue | Disable-ScheduledTask | Out-Null
}
# Never sleep or turn the screen off: the console is a VM's only screen.
powercfg.exe /change standby-timeout-ac 0
powercfg.exe /change monitor-timeout-ac 0

Step 'Done. Install anything every machine should have, then run clean.ps1.'
