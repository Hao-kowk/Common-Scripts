#Requires -Version 5.1
<#
  GetFile.ps1 — 把子文件夹里的文件全部提取到当前目录

  重名处理方案（发现重名时才会询问）：
    1 = 所有文件加序号前缀        001_原文件名.ext
    2 = 所有文件加来源文件夹前缀  子文件夹名_原文件名.ext
    3 = 跳过重名文件，保持原样，最后列在报告里

  其它：回车确认后才动手；结束后写「提取记录.txt」。
#>
[CmdletBinding()]
param(
    [string]$Root,
    [int]$Scheme = 0,
    [switch]$DeleteEmpty,
    [switch]$NonInteractive,
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Say { param($t) Write-Host $t }
function Ok { param($t) Write-Host $t -ForegroundColor Green }
function Warn { param($t) Write-Host $t -ForegroundColor Yellow }
function Bad { param($t) Write-Host $t -ForegroundColor Red }

function Get-UniqueName {
    param([string]$Name, $Taken)
    if (-not $Taken.Contains($Name)) { return $Name }
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Name)
    $ext = [System.IO.Path]::GetExtension($Name)
    $i = 2
    while ($true) {
        $cand = '{0} ({1}){2}' -f $base, $i, $ext
        if (-not $Taken.Contains($cand)) { return $cand }
        $i++
    }
}

function Get-SafeName {
    param([string]$Name)
    foreach ($c in [System.IO.Path]::GetInvalidFileNameChars()) {
        $Name = $Name.Replace([string]$c, '_')
    }
    return $Name.Trim()
}

function Read-Choice {
    param([string]$Prompt, [string]$Pattern, [string]$BadHint)
    for ($i = 0; $i -lt 5; $i++) {
        $a = Read-Host $Prompt
        if ($null -eq $a) { $a = '' }
        $a = $a.Trim().TrimStart([char]0xFEFF).Trim()
        if ($a -match $Pattern) { return $a }
        Warn $BadHint
    }
    return ''
}

# ---------------------------------------------------------------- 定位目录

if (-not $Root -or $Root.Trim() -eq '') { $Root = $PSScriptRoot }
$Root = $Root.Trim().Trim('"').TrimEnd('\')
try { $Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\') }
catch { Bad ('目录不存在：' + $Root); exit 1 }

Say '=========================================='
Say ' 提取文件工具'
Say '=========================================='
Say ('目录：' + $Root)

$toolNames = @('GetFile.bat', 'GetFile.ps1', '提取记录.txt')
$all = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike '*$RECYCLE.BIN*' -and $_.FullName -notlike '*System Volume Information*' })

$rootFiles = @($all | Where-Object {
        ([System.IO.Path]::GetDirectoryName($_.FullName).TrimEnd('\')) -eq $Root -and
        ($toolNames -notcontains $_.Name)
    })
$candidates = @($all | Where-Object {
        ([System.IO.Path]::GetDirectoryName($_.FullName).TrimEnd('\')) -ne $Root
    } | Sort-Object FullName)

Say ('子文件夹里的文件：{0} 个' -f $candidates.Count)
Say ('当前目录已有的文件：{0} 个' -f $rootFiles.Count)

if ($candidates.Count -eq 0) {
    Warn '没有需要提取的文件，退出。'
    return
}

# ---------------------------------------------------------------- 找重名

$taken = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($f in $rootFiles) { [void]$taken.Add($f.Name) }

$groups = @{}
foreach ($f in $candidates) {
    $key = $f.Name.ToLower()
    if (-not $groups.ContainsKey($key)) { $groups[$key] = New-Object 'System.Collections.Generic.List[object]' }
    $groups[$key].Add($f)
}

$dupGroups = @{}
foreach ($k in $groups.Keys) {
    $g = $groups[$k]
    if ($g.Count -gt 1 -or $taken.Contains($g[0].Name)) { $dupGroups[$k] = $g }
}

$dupCount = 0
foreach ($k in $dupGroups.Keys) { $dupCount += $dupGroups[$k].Count }

# ---------------------------------------------------------------- 选方案

$scheme = $Scheme

if ($dupCount -gt 0) {
    Warn ''
    Warn ('◆ 发现 {0} 个重名文件（与当前目录已有文件重名，或它们之间互相重名）：' -f $dupCount)
    foreach ($k in ($dupGroups.Keys | Sort-Object)) {
        foreach ($f in $dupGroups[$k]) { Warn ('    ' + $f.FullName.Substring($Root.Length + 1)) }
    }
    Warn ''
}

if (-not $NonInteractive) {
    if ($dupCount -gt 0) {
        Say '请选择重名处理方案：'
        Say '  1 = 所有文件加序号前缀      001_原文件名.ext'
        Say '  2 = 所有文件加来源文件夹前缀 子文件夹名_原文件名.ext'
        Say '  3 = 跳过重名文件             保持原样，最后列在报告里'
        Say '  0 = 取消'
        $ans = Read-Choice -Prompt '请输入 1 / 2 / 3 / 0' -Pattern '^[0-3]' -BadHint '输入无效，请输入 1、2、3 或 0。'
        if ($ans -eq '') { Bad '多次输入无效，已退出，没有改动任何文件。'; return }
        $scheme = [int]$ans.Substring(0, 1)
        if ($scheme -eq 0) { Say '已取消，没有改动任何文件。'; return }
    }
    else {
        Say ''
        Ok '没有发现重名文件。'
        $ans = Read-Host '按回车开始提取，输入 0 取消'
        if ($null -ne $ans -and ($ans.Trim().TrimStart([char]0xFEFF) -match '^0')) { Say '已取消，没有改动任何文件。'; return }
        $scheme = 0
    }

    if (-not $DeleteEmpty) {
        $a2 = Read-Host '提取完成后，删除变空的子文件夹？(Y/N，直接回车 = N)'
        if ($null -ne $a2 -and ($a2.Trim().TrimStart([char]0xFEFF) -match '^[Yy]')) { $DeleteEmpty = $true }
    }
}
else {
    if ($scheme -eq 0) { $scheme = 3 }
}

# ---------------------------------------------------------------- 生成计划

$plan = New-Object 'System.Collections.Generic.List[object]'
$planned = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($f in $rootFiles) { [void]$planned.Add($f.Name) }

$seq = 0
foreach ($f in $candidates) {
    $skip = $false
    $newName = $f.Name
    $reason = ''

    $key = $f.Name.ToLower()
    $isDup = $dupGroups.ContainsKey($key)

    if ($scheme -eq 3 -and $isDup) {
        $skip = $true
        $reason = '重名，按方案3跳过'
    }
    elseif ($scheme -eq 1) {
        $seq++
        $newName = '{0:D3}_{1}' -f $seq, (Get-SafeName $f.Name)
    }
    elseif ($scheme -eq 2) {
        $rel = $f.FullName.Substring($Root.Length + 1)
        $top = ($rel -split '\\')[0]
        $newName = '{0}_{1}' -f (Get-SafeName $top), (Get-SafeName $f.Name)
    }

    if (-not $skip) { $newName = Get-UniqueName -Name $newName -Taken $planned }

    $plan.Add([pscustomobject]@{
            Source   = $f.FullName
            RelPath  = $f.FullName.Substring($Root.Length + 1)
            NewName  = $newName
            Target   = Join-Path $Root $newName
            Skip     = $skip
            Reason   = $reason
            Seq      = $seq
        })
    if (-not $skip) { [void]$planned.Add($newName) }
}

$moveList = @($plan | Where-Object { -not $_.Skip })
$skipList = @($plan | Where-Object { $_.Skip })

Say ''
Say ('准备提取 {0} 个文件' -f $moveList.Count)
if ($skipList.Count -gt 0) { Warn ('将跳过 {0} 个重名文件' -f $skipList.Count) }

if ($Preview) {
    Say ''
    Say '---- 预览（不会真的移动）----'
    foreach ($p in $moveList) { Say ('  {0}  ->  {1}' -f $p.RelPath, $p.NewName) }
    foreach ($p in $skipList) { Warn ('  [跳过] {0}' -f $p.RelPath) }
    return
}

# ---------------------------------------------------------------- 执行

$done = 0
$failed = 0
foreach ($p in $moveList) {
    try {
        Move-Item -LiteralPath $p.Source -Destination $p.Target -ErrorAction Stop
        $done++
    }
    catch {
        $failed++
        Bad ('  移动失败：{0}（{1}）' -f $p.RelPath, $_.Exception.Message)
    }
}
Ok ('已提取 {0} 个文件' -f $done)
if ($skipList.Count -gt 0) { Warn ('跳过 {0} 个重名文件' -f $skipList.Count) }
if ($failed -gt 0) { Bad ('失败 {0} 个' -f $failed) }

# ---------------------------------------------------------------- 删空文件夹

$removedDirs = 0
if ($DeleteEmpty) {
    $dirs = @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending)
    foreach ($d in $dirs) {
        $left = @(Get-ChildItem -LiteralPath $d.FullName -Recurse -Force -ErrorAction SilentlyContinue)
        if ($left.Count -eq 0) {
            try {
                Remove-Item -LiteralPath $d.FullName -Force -ErrorAction Stop
                $removedDirs++
            }
            catch { }
        }
    }
    Ok ('已删除 {0} 个空文件夹' -f $removedDirs)
}

# ---------------------------------------------------------------- 报告

$schemeName = switch ($scheme) {
    1 { '1 - 所有文件加序号前缀' }
    2 { '2 - 所有文件加来源文件夹前缀' }
    3 { '3 - 跳过重名文件' }
    default { '无重名，直接提取' }
}

$report = Join-Path $Root '提取记录.txt'
$lines = New-Object 'System.Collections.Generic.List[string]'
$lines.Add('提取记录')
$lines.Add(('时间：{0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')))
$lines.Add(('目录：{0}' -f $Root))
$lines.Add(('方案：{0}' -f $schemeName))
$lines.Add(('结果：共发现 {0} 个文件，提取 {1} 个，跳过 {2} 个，失败 {3} 个，删除空文件夹 {4} 个' -f $candidates.Count, $done, $skipList.Count, $failed, $removedDirs))
$lines.Add('')
if ($skipList.Count -gt 0) {
    $lines.Add('【未提取的重名文件】')
    foreach ($p in $skipList) {
        $lines.Add(('  {0}    （原因：{1}，与当前目录中同名文件冲突）' -f $p.RelPath, $p.Reason))
    }
    $lines.Add('')
}
$lines.Add('【明细】')
foreach ($p in $moveList) {
    $lines.Add(('  {0}  ->  {1}' -f $p.RelPath, $p.NewName))
}
$lines.Add('')

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($report, $lines.ToArray(), $utf8)

Say ''
Ok ('完成，报告已写入：{0}' -f $report)
