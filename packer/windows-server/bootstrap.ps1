# First sign-in of the Windows Server template build (autounattend.xml runs it from its CD): installs
# VMware Tools, which has the network adapter's driver, then lets Packer in over WinRM. finish.ps1
# takes WinRM's build-only settings out again before the VM is generalized.
$ErrorActionPreference = 'Stop'
Start-Transcript -Path C:\Windows\Temp\lab-bootstrap.log

# VMware Tools, from ESXi's tools CD (windows.iso), without the restart it asks for.
$tools = Get-PSDrive -PSProvider FileSystem | ForEach-Object { Join-Path $_.Root 'setup64.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tools) { throw "No VMware Tools CD (setup64.exe) found." }
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
