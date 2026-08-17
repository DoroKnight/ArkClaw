$ErrorActionPreference = 'Continue'
$target = 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
$log = 'D:\ArkClaw\build\residual-removal.log'
"start $(Get-Date -Format o)" | Out-File $log -Encoding utf8
if (Test-Path -LiteralPath $target) {
    takeown /f $target /r /d y *>> $log
    icacls $target /grant 'lenovo:(OI)(CI)F' /t /c *>> $log
    Remove-Item -LiteralPath $target -Recurse -Force *>> $log
}
"exists_after=$(Test-Path -LiteralPath $target)" | Out-File $log -Append -Encoding utf8
"done $(Get-Date -Format o)" | Out-File $log -Append -Encoding utf8