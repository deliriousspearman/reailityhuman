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
  - stops Server Manager opening at every sign-in, and never sleeps;
  - with -Office, copies Office's install files in, for the panel's Outlook extra;
  - with -SqlServer, copies SQL Server's install files in, with the Chinook sample database, for
    the panel's SQL Server extra;
  - with -Exchange, copies Exchange Server's install files in and installs everything it needs
    first (Windows features, Visual C++ 2012 and 2013, IIS URL Rewrite, UCMA), for the panel's
    Exchange extra, which then only has to join a domain and run Exchange's setup.
It's safe to re-run. Then install anything every machine should have, and run clean.ps1.

The whole process, including the vCenter steps, is in docs/setup-vsphere.md.

.PARAMETER Msi
The Cloudbase-Init 64-bit MSI (CloudbaseInitSetup_x64.msi), copied onto the VM. Not needed when
Cloudbase-Init is installed already.

.PARAMETER NoSsh
Don't set up OpenSSH Server.

.PARAMETER Office
A folder with the Office Deployment Tool's setup.exe, download.xml and the Office folder it
downloaded (scripts/template/office/download.xml says how). They're copied to C:\LabDeploy\office,
and clones install Outlook from there when it's chosen. Not for Server Core: Outlook needs the desktop.

.PARAMETER SqlServer
SQL Server 2025 Developer edition's install media: the folder with its setup.exe, e.g. the mounted
ISO's drive (docs/setup-vsphere.md says where to get it). It's copied to C:\LabDeploy\sqlserver,
with the Chinook sample database's script (downloaded, so it needs the internet, unless -Chinook gives
it), and clones install
SQL Server from there when it's chosen. Works on Server Core too.

.PARAMETER Chinook
Offline: Chinook_SqlServer.sql (the SQL Server extra's dummy data), already downloaded, e.g. from the
media folder scripts/isos/fetch-media.sh makes. It's checked against the pinned SHA-256 and copied in;
without it, it's downloaded.

.PARAMETER Exchange
Exchange Server SE's install media: the folder with its Setup.exe, e.g. the mounted ISO's drive. It's
copied to C:\LabDeploy\exchange, and its prerequisites are installed (downloaded, so it needs the
internet, unless -ExchangePrereqs gives them). Desktop Experience only.

.PARAMETER ExchangePrereqs
Offline: a folder with Exchange's downloaded prerequisites (vcredist2012_x64.exe, vcredist2013_x64.exe,
rewrite_amd64_en-US.msi), e.g. the media folder's windows\exchange. Each is checked against its pinned
SHA-256 and Microsoft's signature.

.PARAMETER DryRun
Only say what it found and what it would do.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File prepare.ps1 -Msi C:\Users\Administrator\Downloads\CloudbaseInitSetup_x64.msi

.EXAMPLE
powershell -ExecutionPolicy Bypass -File D:\prepare.ps1 -Msi D:\CloudbaseInitSetup_x64.msi -Office D:\office

.EXAMPLE
powershell -ExecutionPolicy Bypass -File D:\prepare.ps1 -Msi D:\CloudbaseInitSetup_x64.msi -SqlServer E:\
#>
[CmdletBinding()]
param(
    [string]$Msi,
    [switch]$NoSsh,
    [string]$Office,
    [string]$SqlServer,
    [string]$Chinook,
    [string]$Exchange,
    [string]$ExchangePrereqs,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$CloudbaseDir = Join-Path $env:ProgramFiles 'Cloudbase Solutions\Cloudbase-Init'
$ConfDir = Join-Path $CloudbaseDir 'conf'
# Where the Outlook extra (backend/extras.yaml) looks for them. Not under C:\ProgramData\lab-deploy,
# which clean.ps1 empties.
$OfficeDir = 'C:\LabDeploy\office'
# Where the SQL Server extra looks for its install files, and for Chinook's script (pinned: its
# release, and the file's SHA-256).
$SqlServerDir = 'C:\LabDeploy\sqlserver'
$ChinookDir = 'C:\LabDeploy\chinook'
$ChinookUrl = 'https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_SqlServer.sql'
$ChinookSha256 = '5ea75c9e925ead917d3fabea6ed3cc8c1ff1d036b61e915c94631aafa2b0802b'
# Where the Exchange extra looks for its install files; and its prerequisites (Microsoft's links, pinned).
$ExchangeDir = 'C:\LabDeploy\exchange'
$ExchangePrereqDir = 'C:\LabDeploy\exchange-prereqs'
$ExchangePrereqFiles = [ordered]@{
    'vcredist2012_x64.exe'    = @('https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/VSU_4/vcredist_x64.exe', '681BE3E5BA9FD3DA02C09D7E565ADFA078640ED66A0D58583EFAD2C1E3CC4064')
    'vcredist2013_x64.exe'    = @('https://download.visualstudio.microsoft.com/download/pr/10912041/cee5d6bca2ddbcd039da727bf4acb48a/vcredist_x64.exe', 'A4BBA7701E355AE29C403431F871A537897C363E215CAFE706615E270984F17C')
    'rewrite_amd64_en-US.msi' = @('https://download.microsoft.com/download/1/2/8/128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_en-US.msi', '37342FF2F585F263F34F48E9DE59EB1051D61015A8E967DBDE4075716230A32A')
}
# The Windows features Exchange's Mailbox role needs (Microsoft's list for Windows Server 2022 and 2025).
$ExchangeFeatures = 'Server-Media-Foundation', 'NET-Framework-45-Features', 'RPC-over-HTTP-proxy', 'RSAT-Clustering',
    'RSAT-Clustering-CmdInterface', 'RSAT-Clustering-Mgmt', 'RSAT-Clustering-PowerShell', 'WAS-Process-Model', 'Web-Asp-Net45',
    'Web-Basic-Auth', 'Web-Client-Auth', 'Web-Digest-Auth', 'Web-Dir-Browsing', 'Web-Dyn-Compression', 'Web-Http-Errors',
    'Web-Http-Logging', 'Web-Http-Redirect', 'Web-Http-Tracing', 'Web-ISAPI-Ext', 'Web-ISAPI-Filter', 'Web-Metabase',
    'Web-Mgmt-Console', 'Web-Mgmt-Service', 'Web-Net-Ext45', 'Web-Request-Monitor', 'Web-Server', 'Web-Stat-Compression',
    'Web-Static-Content', 'Web-Windows-Auth', 'Web-WMI', 'RSAT-ADDS', 'NET-WCF-HTTP-Activation45', 'NET-WCF-Pipe-Activation45'

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
$rpctool = Join-Path $env:ProgramFiles 'VMware\VMware Tools\rpctool.exe'
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
if ($Office) {
    foreach ($file in 'setup.exe', 'download.xml', 'Office\Data\v64.cab') {
        if (-not (Test-Path (Join-Path $Office $file))) {
            throw "$Office has no $file. It needs setup.exe and download.xml, and the Office folder that setup.exe /download download.xml makes."
        }
    }
    $installType = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').InstallationType
    if ($installType -eq 'Server Core') {
        throw 'Outlook needs the desktop, and this is Server Core: leave out -Office.'
    }
}
if ($Exchange) {
    if (-not (Test-Path (Join-Path $Exchange 'Setup.exe')) -or -not (Test-Path (Join-Path $Exchange 'UCMARedist\Setup.exe'))) {
        throw "$Exchange has no Setup.exe and UCMARedist. Give the folder (or mounted ISO) with Exchange Server's install media."
    }
    if (-not $server -or (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').InstallationType -eq 'Server Core') {
        throw 'Exchange is prepared on Windows Server with the Desktop Experience.'
    }
}
if ($SqlServer -and -not (Test-Path (Join-Path $SqlServer 'setup.exe'))) {
    throw "$SqlServer has no setup.exe. Give the folder (or mounted ISO) with SQL Server's install media."
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
if ($Office) {
    $size = (Get-ChildItem -Path $Office -Recurse -File | Measure-Object -Property Length -Sum).Sum
    Note ("Office files: to copy from $Office to $OfficeDir ({0:N1} GB)" -f ($size / 1GB))
}
if ($SqlServer) {
    $size = (Get-ChildItem -Path $SqlServer -Recurse -File | Measure-Object -Property Length -Sum).Sum
    Note ("SQL Server files: to copy from $SqlServer to $SqlServerDir ({0:N1} GB), and Chinook to $ChinookDir" -f ($size / 1GB))
}
if ($Exchange) {
    Note "Exchange: its files from $Exchange to $ExchangeDir, and its prerequisites installed"
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
# During sysprep (specialize): on Server, the computer name, which takes effect at the restart that
# follows. Not on client Windows (10, 11): its first-run setup (OOBE), after this, renames a machine
# whose answer file names no computer to a random DESKTOP-..., and the template's can't name each
# clone. There the service names it instead, after Setup (and a restart), as the name step would
# otherwise count as done.
$unattendPlugins = 'cloudbaseinit.plugins.windows.extendvolumes.ExtendVolumesPlugin'
if ($server) { $unattendPlugins = "cloudbaseinit.plugins.common.sethostname.SetHostNamePlugin,$unattendPlugins" }
$unattend = $common + "`r`n" + @"
log_file=cloudbase-init-unattend.log
plugins=$unattendPlugins
allow_reboot=false
stop_service_on_exit=false
"@
# The service, at each boot (from SetupComplete.cmd on, below): the name (on Server, already set; on
# client Windows, set here, with a restart), then the panel's first-boot script, which it runs once
# per instance.
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
# The service starts only once Windows Setup has finished on a clone (SetupComplete.cmd, which Setup
# runs as its last step). Started any earlier, it can run during Setup itself, as on Windows 11: it
# set the name and restarted mid-Setup, the unattend stage then skipped the name as done, and Setup
# gave the machine a random DESKTOP-... one.
Set-Service -Name cloudbase-init -StartupType Manual
$setupScripts = Join-Path $env:SystemRoot 'Setup\Scripts'
New-Item -ItemType Directory -Force -Path $setupScripts | Out-Null
Set-Content -Path (Join-Path $setupScripts 'SetupComplete.cmd') -Encoding ascii -Value @'
@echo off
rem Written by the lab panel's scripts/template/prepare.ps1: Cloudbase-Init's service, from now on.
sc.exe config cloudbase-init start= auto
sc.exe start cloudbase-init
'@

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
        try {
            Add-WindowsCapability -Online -Name $sshCapability.Name | Out-Null
        } catch {
            throw ("Couldn't install OpenSSH Server ($($_.Exception.Message)). Without internet access, Windows " +
                'needs its Features on Demand media for that: add -Source <its folder> to Add-WindowsCapability ' +
                "by hand, or re-run with -NoSsh and take ssh out of the template's access in templates.yaml.")
        }
    }
    Set-Service -Name sshd -StartupType Automatic
    if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
    }
    # Every network profile: Windows' own rule only covers private networks, and a new machine's
    # network is public.
    Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Profile Any -Enabled True
    New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
    Set-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
    # Started on each clone by the panel's first-boot script, once it has its own host keys.
}

# Office --------------------------------------------------------------------------------------------------

if ($Office) {
    Step "Copying Office's install files to $OfficeDir"
    # /MIR: a re-run leaves an exact copy. Robocopy's exit codes below 8 all mean success.
    robocopy.exe $Office $OfficeDir /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Copying $Office to $OfficeDir failed (robocopy exit code $LASTEXITCODE)."
    }
}

# SQL Server ----------------------------------------------------------------------------------------------

if ($SqlServer) {
    Step "Copying SQL Server's install files to $SqlServerDir"
    robocopy.exe $SqlServer $SqlServerDir /MIR /NFL /NDL /NJH /NJS /NP /XD 'System Volume Information' | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Copying $SqlServer to $SqlServerDir failed (robocopy exit code $LASTEXITCODE)."
    }
    New-Item -ItemType Directory -Force -Path $ChinookDir | Out-Null
    $chinookFile = Join-Path $ChinookDir 'Chinook_SqlServer.sql'
    if ($Chinook) {
        Step "Copying the Chinook sample database to $ChinookDir"
        Copy-Item -Path $Chinook -Destination $chinookFile -Force
        $from = $Chinook
    } else {
        Step "Downloading the Chinook sample database to $ChinookDir"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $ChinookUrl -OutFile $chinookFile -UseBasicParsing
        $from = $ChinookUrl
    }
    if ((Get-FileHash -Path $chinookFile -Algorithm SHA256).Hash -ne $ChinookSha256) {
        Remove-Item -Path $chinookFile
        throw "$from isn't the file expected (its SHA-256 differs)."
    }
}

# Exchange ------------------------------------------------------------------------------------------------

if ($Exchange) {
    Step "Copying Exchange's install files to $ExchangeDir"
    robocopy.exe $Exchange $ExchangeDir /MIR /NFL /NDL /NJH /NJS /NP /XD 'System Volume Information' | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Copying $Exchange to $ExchangeDir failed (robocopy exit code $LASTEXITCODE)."
    }

    Step "Exchange's prerequisites"
    New-Item -ItemType Directory -Force -Path $ExchangePrereqDir | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    foreach ($name in $ExchangePrereqFiles.Keys) {
        $url, $sha256 = $ExchangePrereqFiles[$name]
        $file = Join-Path $ExchangePrereqDir $name
        if ($ExchangePrereqs -and (Test-Path (Join-Path $ExchangePrereqs $name))) {
            Copy-Item -Path (Join-Path $ExchangePrereqs $name) -Destination $file -Force
        } elseif (-not (Test-Path $file)) {
            Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing
        }
        if ((Get-FileHash -Path $file -Algorithm SHA256).Hash -ne $sha256) {
            Remove-Item -Path $file
            throw "$name isn't the file expected (its SHA-256 differs)."
        }
        $signature = Get-AuthenticodeSignature -FilePath $file
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*O=Microsoft Corporation*') {
            throw "$name isn't signed by Microsoft."
        }
    }
    Note 'Windows features'
    $features = Get-WindowsFeature -Name $ExchangeFeatures | Where-Object { -not $_.Installed } | ForEach-Object Name
    if ($features) {
        $result = Install-WindowsFeature -Name $features
        if (-not $result.Success) { throw "Installing Exchange's Windows features failed." }
    }
    # Each installer's exit code: 0, or 3010 (installed, a restart needed: sysprep's shutdown is one).
    function Install-Prereq([string]$Name, [string]$FilePath, [string[]]$Arguments) {
        Note $Name
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -Wait -PassThru
        if ($process.ExitCode -notin 0, 1638, 3010) {
            throw "$Name failed to install (exit code $($process.ExitCode))."
        }
    }
    Install-Prereq 'Visual C++ 2012' (Join-Path $ExchangePrereqDir 'vcredist2012_x64.exe') '/install', '/quiet', '/norestart'
    Install-Prereq 'Visual C++ 2013' (Join-Path $ExchangePrereqDir 'vcredist2013_x64.exe') '/install', '/quiet', '/norestart'
    Install-Prereq 'IIS URL Rewrite' msiexec.exe '/i', "`"$(Join-Path $ExchangePrereqDir 'rewrite_amd64_en-US.msi')`"", '/qn', '/norestart'
    Install-Prereq 'Unified Communications Managed API 4.0' (Join-Path $ExchangeDir 'UCMARedist\Setup.exe') '/passive', '/norestart'
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
