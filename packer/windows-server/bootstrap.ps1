# First sign-in of the Windows Server template build (autounattend.xml runs it from its CD): installs
# VMware Tools, which has the network adapter's driver, then lets Packer in over WinRM. finish.ps1
# takes WinRM's build-only settings out again before the VM is generalized.
$ErrorActionPreference = 'Stop'
Start-Transcript -Path C:\Windows\Temp\lab-bootstrap.log

# VMware Tools, from ESXi's tools CD (windows.iso, labelled "VMware Tools"), without the restart it
# asks for. Older Tools have setup64.exe; newer ones only setup.exe, which the Windows and SQL Server
# CDs have too, hence the label.
$cd = Get-Volume | Where-Object { $_.DriveType -eq 'CD-ROM' -and $_.FileSystemLabel -eq 'VMware Tools' } | Select-Object -First 1
if (-not $cd) { throw "No VMware Tools CD (labelled 'VMware Tools') found." }
$tools = 'setup64.exe', 'setup.exe' | ForEach-Object { "$($cd.DriveLetter):\$_" } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tools) { throw "The VMware Tools CD has no setup64.exe or setup.exe." }
$p = Start-Process -FilePath $tools -ArgumentList '/S', '/v"/qn REBOOT=R"' -Wait -PassThru
if ($p.ExitCode -notin 0, 3010) { throw "VMware Tools setup failed (exit code $($p.ExitCode))." }

# The network is now up: make it private, which WinRM's firewall rules need.
for ($i = 0; $i -lt 60 -and -not (Get-NetConnectionProfile -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Seconds 5 }
Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private

# WinRM over HTTP with basic sign-in: for the build only, on the build network.
winrm quickconfig -quiet -force
Set-Item -Path WSMan:\localhost\Service\AllowUnencrypted -Value $true
Set-Item -Path WSMan:\localhost\Service\Auth\Basic -Value $true
Set-Item -Path WSMan:\localhost\MaxTimeoutms -Value 1800000
New-NetFirewallRule -Name 'LabBuildWinRM' -DisplayName 'WinRM for the template build' -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow | Out-Null
Set-Service -Name WinRM -StartupType Automatic
Restart-Service -Name WinRM
Stop-Transcript
