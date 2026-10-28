# Older Windows Server for the template build (windows-server.pkr.hcl runs it over WinRM, before
# provision.ps1): adds what 2016 and 2012 R2 lack and the rest of the build expects. On 2019 and later
# it has nothing to do.
#   - 2012 R2: the Universal C Runtime (KB2999226), which Cloudbase-Init's Python needs; .NET Framework
#     4.8, which WMF 5.1 needs; and WMF 5.1 (KB3191564), for PowerShell 5.1, whose local-account
#     commands (New-LocalUser and so on) the panel's first-boot script uses. A restart follows (the
#     next provisioner).
#   - 2016 and 2012 R2: OpenSSH Server, from Microsoft's Win32-OpenSSH MSI. Windows only has it as a
#     feature from 2019 (build 17763); prepare.ps1 then configures it as it does that one.
# From the build CD's windows\legacy folder (scripts/isos/fetch-media.sh) when it's there; otherwise
# downloaded. Each file is checked against its pinned SHA-256 and Microsoft's signature.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# 2012 R2's and 2016's PowerShell asks for TLS 1.0, which Microsoft's and GitHub's servers refuse.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Dir = 'C:\LabBuild\legacy'
$Files = [ordered]@{
    'Windows8.1-KB2999226-x64.msu'         = @('https://download.microsoft.com/download/9/6/F/96FD0525-3DDF-423D-8845-5F92F4A6883E/Windows8.1-KB2999226-x64.msu', '9F707096C7D279ED4BC2A40BA695EFAC69C20406E0CA97E2B3E08443C6381D15')
    'ndp48-x86-x64-allos-enu.exe'          = @('https://download.visualstudio.microsoft.com/download/pr/2d6bb6b2-226a-4baa-bdec-798822606ff1/8494001c276a4b96804cde7829c04d7f/ndp48-x86-x64-allos-enu.exe', '68C9986A8DCC0214D909AA1F31BEE9FB5461BB839EDCA996A75B08DDFFC1483F')
    'Win8.1AndW2K12R2-KB3191564-x64.msu'   = @('https://download.microsoft.com/download/6/F/5/6F5FF66C-6775-42B0-86C4-47D41F2DA187/Win8.1AndW2K12R2-KB3191564-x64.msu', 'A8D788FA31B02A999CC676FB546FC782E86C2A0ACD837976122A1891CEEE42C0')
    'OpenSSH-Win64-v9.8.3.0.msi'           = @('https://github.com/PowerShell/Win32-OpenSSH/releases/download/v9.8.3.0p2-Preview/OpenSSH-Win64-v9.8.3.0.msi', 'C8A8C7E21136A099665C2FAD9ACCB41152D129466B719EA71678BAB665E03389')
}

function Get-Prereq([string]$Name) {
    $url, $sha256 = $Files[$Name]
    $file = Join-Path $Dir $Name
    $media = Get-PSDrive -PSProvider FileSystem | ForEach-Object { Join-Path $_.Root "windows\legacy\$Name" } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($media) {
        Copy-Item -Path $media -Destination $file -Force
    } elseif (-not (Test-Path $file)) {
        Write-Host "==> Downloading $Name"
        Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing
    }
    if ((Get-FileHash -Path $file -Algorithm SHA256).Hash -ne $sha256) {
        Remove-Item -Path $file
        throw "$Name isn't the file expected (its SHA-256 differs)."
    }
    $signature = Get-AuthenticodeSignature -FilePath $file
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*O=Microsoft Corporation*') {
        throw "$Name isn't signed by Microsoft ($($signature.Status))."
    }
    $file
}
# Exit codes that mean done: 0; 3010 and 1641 (a restart needed, which follows); 2359302 (wusa: already
# installed); 1638 (msiexec: already installed).
function Install-Prereq([string]$What, [string]$FilePath, [string[]]$Arguments) {
    Write-Host "==> Installing $What"
    $p = Start-Process -FilePath $FilePath -ArgumentList $Arguments -Wait -PassThru
    if ($p.ExitCode -notin 0, 1638, 1641, 3010, 2359302) {
        throw "$What failed to install (exit code $($p.ExitCode))."
    }
}

$version = [Version](Get-CimInstance Win32_OperatingSystem).Version
if ($version -ge [Version]'10.0.17763') {
    Write-Host '==> Windows Server 2019 or later: nothing to add'
    return
}
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

if ($version -lt [Version]'10.0') {
    $ucrt = Get-Prereq 'Windows8.1-KB2999226-x64.msu'
    Install-Prereq 'the Universal C Runtime (KB2999226)' wusa.exe "`"$ucrt`"", '/quiet', '/norestart'
    $ndp = Get-Prereq 'ndp48-x86-x64-allos-enu.exe'
    Install-Prereq '.NET Framework 4.8' $ndp '/q', '/norestart'
    $wmf = Get-Prereq 'Win8.1AndW2K12R2-KB3191564-x64.msu'
    Install-Prereq 'WMF 5.1 (KB3191564)' wusa.exe "`"$wmf`"", '/quiet', '/norestart'
}

if (-not (Get-Service -Name sshd -ErrorAction SilentlyContinue)) {
    $ssh = Get-Prereq 'OpenSSH-Win64-v9.8.3.0.msi'
    Install-Prereq 'OpenSSH Server (Win32-OpenSSH 9.8.3)' msiexec.exe '/i', "`"$ssh`"", 'ADDLOCAL=Server', '/qn', '/norestart'
    # Host keys are made on each clone (the panel's first-boot script starts it there).
    Stop-Service -Name sshd -ErrorAction SilentlyContinue
    Set-Service -Name sshd -StartupType Manual
}
