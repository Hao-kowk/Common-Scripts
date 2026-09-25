# ============================================================
#  补上官方安装程序没有加的那一条 PATH
#  作用：让 npm install -g 装的全局命令行工具能被系统找到
#  用法：双击同目录下的「补环境变量.bat」
#  只改「用户变量」，不需要管理员权限，改前先备份
#
#  这一版会先把注册表里的真实值打印出来，再决定动不动手，
#  判断依据是看得见的，不是猜的。
# ============================================================

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$ErrorActionPreference = 'Continue'

$npmDir      = Join-Path $env:APPDATA 'npm'
$npmDirLower = $npmDir.TrimEnd('\').ToLowerInvariant()
$appendValue = '%APPDATA%\npm'

Write-Host ""
Write-Host "=============================================="
Write-Host "  补 PATH：npm 全局命令目录"
Write-Host "=============================================="
Write-Host ""
Write-Host "这个目录的实际位置："
Write-Host "  $npmDir"
Write-Host ("目录现在存在吗：" + (Test-Path -LiteralPath $npmDir))
Write-Host ""

# ---------- 读注册表原始值（不展开 %变量%） ----------
$raw = $null
$key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $false)
if ($key) {
  $raw = $key.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
  $key.Close()
}

Write-Host "原始用户 PATH（注册表里的真实内容，原样打印）："
Write-Host "  [$raw]"
Write-Host ""

if (-not $raw) {
  Write-Host "读不到用户 PATH 的注册表值，脚本停止。" -ForegroundColor Red
  Write-Host "请把上面这段输出发我。"
  Write-Host ""
  exit 1
}

# ---------- 判断那一条是否已经在里面 ----------
$matched = $null
foreach ($e in ($raw -split ';')) {
  if (-not $e.Trim()) { continue }
  $expanded = [Environment]::ExpandEnvironmentVariables($e).Trim().TrimEnd('\').ToLowerInvariant()
  if ($expanded -eq $npmDirLower) { $matched = $e }
}

if ($matched) {
  Write-Host "判定：已经在 PATH 里了。命中的原始条目是：" -ForegroundColor Green
  Write-Host "  [$matched]"
  Write-Host ""
  Write-Host "所以这一台机器不需要再做任何事。"
  Write-Host ""
  exit 0
}

Write-Host "判定：注册表的用户 PATH 里没有这一条，需要补上。" -ForegroundColor Yellow
Write-Host ""

# ---------- 备份 ----------
$backup = Join-Path $PSScriptRoot ('PATH_backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.txt')
try {
  Set-Content -LiteralPath $backup -Value ("用户 PATH 原值：" + $raw) -Encoding UTF8
  Write-Host "已备份原值到：$backup"
} catch {
  Write-Host "备份失败，为安全起见不继续。" -ForegroundColor Red
  exit 1
}

# ---------- 写入（保留可展开类型，不破坏原来的 %变量%） ----------
$newRaw = $raw.TrimEnd(';') + ';' + $appendValue

try {
  $keyW = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
  if (-not $keyW) { throw "无法以可写方式打开 HKCU\Environment" }
  $keyW.SetValue('Path', $newRaw, [Microsoft.Win32.RegistryValueKind]::ExpandString)
  $keyW.Close()
} catch {
  Write-Host "写入失败：$($_.Exception.Message)" -ForegroundColor Red
  Write-Host ""
  Write-Host "这通常说明当前进程没有权限改注册表。"
  Write-Host "请确认是直接双击 .bat 运行的，把上面这段输出发我。"
  Write-Host ""
  exit 1
}

# ---------- 通知系统刷新（新开的窗口立刻拿到新 PATH） ----------
$broadcast = $false
try {
  if (-not ('NodeFix.Native' -as [type])) {
    Add-Type -Namespace NodeFix -Name Native -MemberDefinition @'
[DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
  }
  $out = [UIntPtr]::Zero
  [NodeFix.Native]::SendMessageTimeout([IntPtr]0xffff, 0x001A, [UIntPtr]::Zero, 'Environment', 2, 3000, [ref]$out) | Out-Null
  $broadcast = $true
} catch { $broadcast = $false }

# ---------- 复核：重新读一遍注册表，把结果打出来当证据 ----------
$after = $null
$key2 = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $false)
if ($key2) {
  $after = $key2.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
  $key2.Close()
}

Write-Host ""
Write-Host "写入后的原始用户 PATH："
Write-Host "  [$after]"
Write-Host ""

$ok = $false
if ($after) {
  foreach ($e in ($after -split ';')) {
    if (-not $e.Trim()) { continue }
    $expanded = [Environment]::ExpandEnvironmentVariables($e).Trim().TrimEnd('\').ToLowerInvariant()
    if ($expanded -eq $npmDirLower) { $ok = $true }
  }
}

if ($ok) {
  Write-Host "结果：已写入，复核通过。" -ForegroundColor Green
  if ($broadcast) {
    Write-Host "已通知系统刷新，新开的 cmd 窗口应该立刻生效。"
  } else {
    Write-Host "刷新通知没发出去（不影响结果），重开一个 cmd 窗口或重启一次即可。"
  }
} else {
  Write-Host "结果：写入后复核没通过，请把上面这段输出发我。" -ForegroundColor Red
}
Write-Host ""
