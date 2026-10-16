# The Windows Server template build's shutdown (windows-server.pkr.hcl): takes out what only the build
# needed, then runs clean.ps1, which generalizes the VM with sysprep and shuts it down.
$ErrorActionPreference = 'Stop'

# WinRM back to Windows' defaults: no unencrypted traffic, no basic sign-in, no extra firewall rule.
# (This command keeps running; Packer only waits for the VM to power off from here.)
Set-Item -Path WSMan:\localhost\Service\AllowUnencrypted -Value $false
Set-Item -Path WSMan:\localhost\Service\Auth\Basic -Value $false
Remove-NetFirewallRule -Name 'LabBuildWinRM' -ErrorAction SilentlyContinue

# The build's own files: prepare.ps1 has copied what clones need to C:\LabDeploy.
$clean = Join-Path $env:TEMP 'clean.ps1'
Copy-Item -Path 'C:\LabBuild\clean.ps1' -Destination $clean -Force
Remove-Item -Path 'C:\LabBuild' -Recurse -Force
Remove-Item -Path 'C:\Windows\Temp\lab-bootstrap.log' -ErrorAction SilentlyContinue

& $clean -Yes
