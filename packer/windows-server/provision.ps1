# Prepares the Windows Server template build (windows-server.pkr.hcl runs it over WinRM): gathers what
# prepare.ps1 needs, then runs it. From the build's CD (this script's own, with prepare.ps1 and
# clean.ps1, and for offline builds the media folder's windows\ from scripts/isos/fetch-media.sh) and
# SQL Server's ISO; otherwise downloaded.
#
# Environment (set by Packer): LAB_EDITION desktop or core; LAB_OFFICE yes/no (desktop only);
# LAB_SQLSERVER yes/no; LAB_EXCHANGE yes/no.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is many times slower with it
# 2016's and 2012 R2's PowerShell asks for TLS 1.0, which GitHub and Microsoft refuse.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Build = 'C:\LabBuild'
$CloudbaseUrl = 'https://github.com/cloudbase/cloudbase-init/releases/download/1.1.9/CloudbaseInitSetup_1_1_9_x64.msi'
$CloudbaseSha256 = 'FFBF80515A7311ED00800276A6AF7AAB23B41D7ACF13E79CE3D2D56844F638F7'
# The Office Deployment Tool's setup.exe, at Microsoft's stable address.
$OdtUrl = 'https://officecdn.microsoft.com/pr/wsus/setup.exe'

function Find-OnCd([string]$Path) {
    Get-PSDrive -PSProvider FileSystem | ForEach-Object { Join-Path $_.Root $Path } | Where-Object { Test-Path $_ } | Select-Object -First 1
}
function Get-Checked([string]$Url, [string]$OutFile, [string]$Sha256) {
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
    if ($Sha256 -and (Get-FileHash -Path $OutFile -Algorithm SHA256).Hash -ne $Sha256) {
        throw "$Url isn't the file expected (its SHA-256 differs)."
    }
}

New-Item -ItemType Directory -Force -Path $Build | Out-Null
$prepare = Find-OnCd 'prepare.ps1'
if (-not $prepare) { throw "The build's CD (prepare.ps1) isn't attached." }
$cd = Split-Path -Parent $prepare
Copy-Item -Path (Join-Path $cd '*.ps1') -Destination $Build -Force
# Offline builds: what would otherwise be downloaded, from the CD's windows folder (fetch-media.sh's).
$media = Join-Path $cd 'windows'
# By name, as a hashtable: an array of '-Name' strings would reach a script as positional values.
$prepareArgs = @{}

# Cloudbase-Init
$msi = Join-Path $Build 'CloudbaseInitSetup_x64.msi'
if (Test-Path (Join-Path $media 'cloudbase-init\CloudbaseInitSetup_x64.msi')) {
    Copy-Item (Join-Path $media 'cloudbase-init\CloudbaseInitSetup_x64.msi') $msi
    if ((Get-FileHash -Path $msi -Algorithm SHA256).Hash -ne $CloudbaseSha256) {
        throw "The media folder's Cloudbase-Init isn't version 1.1.9 (its SHA-256 differs): run fetch-media.sh again."
    }
} else {
    Write-Host '==> Downloading Cloudbase-Init'
    Get-Checked $CloudbaseUrl $msi $CloudbaseSha256
}
$prepareArgs.Msi = $msi

# Office, for the Outlook extra (desktop only)
if ($env:LAB_OFFICE -eq 'yes') {
    if (Test-Path (Join-Path $media 'office\setup.exe')) {
        $office = Join-Path $media 'office'
    } else {
        $office = Join-Path $Build 'office'
        New-Item -ItemType Directory -Force -Path $office | Out-Null
        Write-Host "==> Downloading Office's files (2-3 GB; a while)"
        Get-Checked $OdtUrl (Join-Path $office 'setup.exe') $null
        Copy-Item -Path (Join-Path $cd 'download.xml') -Destination $office
        $p = Start-Process -FilePath (Join-Path $office 'setup.exe') -ArgumentList '/download', 'download.xml' -WorkingDirectory $office -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "Office's download failed (exit code $($p.ExitCode))." }
    }
    $prepareArgs.Office = $office
}

# SQL Server, from its ISO in a CD drive
if ($env:LAB_SQLSERVER -eq 'yes') {
    $sql = Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path (Join-Path $_.Root 'x64\setup') } | ForEach-Object { $_.Root } | Select-Object -First 1
    if (-not $sql) { throw "SQL Server's ISO isn't attached." }
    $prepareArgs.SqlServer = $sql
    $chinook = Join-Path $media 'chinook\Chinook_SqlServer.sql'
    if (Test-Path $chinook) { $prepareArgs.Chinook = $chinook }
}

# Exchange, from its ISO in a CD drive; its prerequisites from the media folder offline
if ($env:LAB_EXCHANGE -eq 'yes') {
    $exchange = Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path (Join-Path $_.Root 'UCMARedist\Setup.exe') } | ForEach-Object { $_.Root } | Select-Object -First 1
    if (-not $exchange) { throw "Exchange's ISO isn't attached." }
    $prepareArgs.Exchange = $exchange
    if (Test-Path (Join-Path $media 'exchange')) { $prepareArgs.ExchangePrereqs = Join-Path $media 'exchange' }
}

Write-Host "==> prepare.ps1 $(($prepareArgs.GetEnumerator() | ForEach-Object { "-$($_.Key) $($_.Value)" }) -join ' ')"
& (Join-Path $Build 'prepare.ps1') @prepareArgs
