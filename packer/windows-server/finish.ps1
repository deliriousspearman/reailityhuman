# The Windows Server template build's shutdown (windows-server.pkr.hcl): takes out what only the build
# needed, then runs clean.ps1, which generalizes the VM with sysprep and shuts it down.
#
# Packer runs this over WinRM and reads its output over WinRM, so it can't switch WinRM's build
# settings off itself (Packer's next request would be refused), and anything it starts dies with the
# WinRM session. So it hands the work to a scheduled task, as SYSTEM, a few seconds later, and returns;
# Packer then waits for the VM to power off.
$ErrorActionPreference = 'Stop'

$work = 'C:\Windows\Temp\lab-finish'
New-Item -ItemType Directory -Force -Path $work | Out-Null
Copy-Item -Path 'C:\LabBuild\clean.ps1' -Destination $work -Force
Set-Content -Path (Join-Path $work 'finish-task.ps1') -Encoding ascii -Value @'
$ErrorActionPreference = 'Stop'
Start-Transcript -Path C:\Windows\Temp\lab-finish\finish.log
# WinRM back to Windows' defaults: no unencrypted traffic, no basic sign-in, no extra firewall rule.
Set-Item -Path WSMan:\localhost\Service\AllowUnencrypted -Value $false
Set-Item -Path WSMan:\localhost\Service\Auth\Basic -Value $false
Remove-NetFirewallRule -Name 'LabBuildWinRM' -ErrorAction SilentlyContinue
# The build's own files: prepare.ps1 has copied what clones need to C:\LabDeploy.
Remove-Item -Path 'C:\LabBuild' -Recurse -Force
Remove-Item -Path 'C:\Windows\Temp\lab-bootstrap.log' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'LabBuildFinish' -Confirm:$false
Stop-Transcript
# Sysprep, which shuts the VM down. (C:\Windows\Temp is emptied by sysprep's own clean-up.) Its
# output in clean.log: if the VM doesn't shut down, that says why (build with -on-error=abort to look).
& C:\Windows\Temp\lab-finish\clean.ps1 -Yes *> C:\Windows\Temp\lab-finish\clean.log
'@

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $work\finish-task.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(15)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'LabBuildFinish' -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Write-Host '==> Finishing in a scheduled task: WinRM back to defaults, then sysprep (the VM shuts down)'
