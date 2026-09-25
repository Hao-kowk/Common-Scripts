# 视频音量处理工具（ffmpeg 封装）
# 作用：把视频里突然变得很大的音量段落压下去，其余部分尽量不动，并自动检查导出结果。
# 用法见同目录下的《使用说明.txt》

[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$InputPath,

    # 0 = 未指定（会询问）, 1/2/3 = 强度, 9 = 只检查不处理
    [int]$Mode = 0,

    [string]$OutDir,

    [switch]$NoCheck,

    [int]$AudioBitrate = 192,

    # 已经有处理结果的视频是否重新处理
    [switch]$Overwrite,

    # 不询问，直接按参数执行（自动化用）
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Continue'

$PRESETS = [ordered]@{
    '1' = [pscustomobject]@{ Name = '温和'; Filter = 'acompressor=threshold=-13dB:ratio=5:attack=1:release=250' }
    '2' = [pscustomobject]@{ Name = '明显'; Filter = 'acompressor=threshold=-16dB:ratio=6:attack=1:release=250:detection=peak' }
    '3' = [pscustomobject]@{ Name = '强力'; Filter = 'acompressor=threshold=-18dB:ratio=10:attack=1:release=300' }
}

$VIDEO_EXT = @('.mp4', '.mkv', '.mov', '.flv', '.ts', '.avi', '.m4v', '.webm', '.wmv', '.mpg', '.mpeg', '.m2ts', '.rmvb')

function Write-Info { param($Text) Write-Host $Text }
function Write-Ok { param($Text) Write-Host $Text -ForegroundColor Green }
function Write-Warn2 { param($Text) Write-Host $Text -ForegroundColor Yellow }
function Write-Bad { param($Text) Write-Host $Text -ForegroundColor Red }

function Find-Tool {
    param([string]$Name)
    $cands = @(
        (Join-Path $PSScriptRoot ("ffmpeg\bin\{0}.exe" -f $Name)),
        (Join-Path $PSScriptRoot ("{0}.exe" -f $Name)),
        ("C:\Users\Halpc_TUF\Documents\Codex\ffmpeg\ffmpeg-9.0.1-essentials_build\bin\{0}.exe" -f $Name),
        ("C:\ffmpeg\bin\{0}.exe" -f $Name)
    )
    foreach ($c in $cands) { if (Test-Path -LiteralPath $c) { return $c } }
    $g = Get-Command ("{0}.exe" -f $Name) -ErrorAction SilentlyContinue
    if ($g) { return $g.Source }
    return $null
}

function Format-Db {
    param($Value)
    if ($null -eq $Value) { return '未知' }
    return ('{0:N1} dB' -f [double]$Value)
}

function Format-Sec {
    param([int]$Seconds)
    return ([timespan]::FromSeconds($Seconds)).ToString('hh\:mm\:ss')
}

function Get-LastNumber {
    param([string]$Text, [string]$Pattern)
    $ms = [regex]::Matches($Text, $Pattern)
    if ($ms.Count -eq 0) { return $null }
    return [double]$ms[$ms.Count - 1].Groups[1].Value
}

function Probe-File {
    param([string]$File)
    $raw = & $script:ffprobe -v error -print_format json -show_format -show_streams $File 2>$null | Out-String
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    try { return ($raw | ConvertFrom-Json) } catch { return $null }
}

function Get-Level {
    param([string]$File)
    $out = & $script:ffmpeg -hide_banner -nostdin -i $File -vn -af 'astats=metadata=0,volumedetect' -f null - 2>&1 | Out-String
    return [pscustomobject]@{
        Mean = (Get-LastNumber $out 'mean_volume:\s*(-?[\d.]+)')
        Max  = (Get-LastNumber $out 'max_volume:\s*(-?[\d.]+)')
        NaN  = (Get-LastNumber $out 'Number of NaNs:\s*(-?[\d.]+)')
        Inf  = (Get-LastNumber $out 'Number of Infs:\s*(-?[\d.]+)')
    }
}

function Get-TailLevel {
    param([string]$File, [int]$Seconds = 30)
    $out = & $script:ffmpeg -hide_banner -nostdin -sseof "-$Seconds" -i $File -vn -af 'volumedetect' -f null - 2>&1 | Out-String
    return [pscustomobject]@{
        Mean = (Get-LastNumber $out 'mean_volume:\s*(-?[\d.]+)')
        Max  = (Get-LastNumber $out 'max_volume:\s*(-?[\d.]+)')
    }
}

function Get-DecodeErrors {
    param([string]$File)
    $out = & $script:ffmpeg -v error -nostdin -i $File -vn -f null - 2>&1
    return @($out | ForEach-Object { "$_" } | Where-Object { $_.Trim() -ne '' })
}

function Get-SecondPeaks {
    param([string]$File)
    $tmpName = 'peaks_{0}.txt' -f ([guid]::NewGuid().ToString('N'))
    $tmpDir = [System.IO.Path]::GetTempPath()
    $tmpPath = Join-Path $tmpDir $tmpName
    $list = New-Object 'System.Collections.Generic.List[double]'
    Push-Location $tmpDir
    try {
        $filter = 'asetnsamples=n=48000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level:file={0}' -f $tmpName
        & $script:ffmpeg -hide_banner -nostdin -i $File -vn -af $filter -f null - 2>$null | Out-Null
        if (Test-Path -LiteralPath $tmpPath) {
            foreach ($line in [System.IO.File]::ReadLines($tmpPath)) {
                $i = $line.IndexOf('Peak_level=')
                if ($i -ge 0) {
                    $x = $line.Substring($i + 11).Trim()
                    if ($x -match '[a-zA-Z]') { $list.Add(-200.0) } else { $list.Add([double]$x) }
                }
            }
        }
    }
    finally {
        Pop-Location
        Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue
    }
    return $list.ToArray()
}

function Convert-PathList {
    param([string[]]$Items, [switch]$AllowProcessed)
    $found = New-Object 'System.Collections.Generic.List[string]'
    foreach ($it in $Items) {
        if ([string]::IsNullOrWhiteSpace($it)) { continue }
        $p = $it.Trim().Trim('"')
        if (-not (Test-Path -LiteralPath $p)) {
            Write-Warn2 ('  路径不存在，跳过：{0}' -f $p)
            continue
        }
        $item = Get-Item -LiteralPath $p
        if ($item.PSIsContainer) {
            Get-ChildItem -LiteralPath $item.FullName -Recurse -File | ForEach-Object {
                if (($VIDEO_EXT -contains $_.Extension.ToLower()) -and ($_.FullName -notmatch '\\_处理后\\') -and ($_.BaseName -notmatch '_音量压缩$')) {
                    $found.Add($_.FullName)
                }
            }
        }
        else {
            if ((-not $AllowProcessed) -and ($item.BaseName -match '_音量压缩$')) {
                Write-Warn2 ('  已经是处理结果，跳过：{0}' -f $item.Name)
                continue
            }
            $found.Add($item.FullName)
        }
    }
    return @($found | Select-Object -Unique)
}

function Invoke-Render {
    param([string]$File, [string]$OutFile, [string]$Filter, [int]$Bitrate)
    $ffargs = @(
        '-hide_banner', '-nostdin',
        '-i', $File,
        '-map', '0:v:0', '-map', '0:a:0',
        '-c:v', 'copy',
        '-af', $Filter,
        '-c:a', 'aac', '-b:a', ("{0}k" -f $Bitrate),
        '-y', $OutFile
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $nextReport = 0.0
    & $script:ffmpeg @ffargs 2>&1 | ForEach-Object {
        $line = "$_"
        if ($line -match 'time=(\d+:\d+:\d+)') {
            if ($sw.Elapsed.TotalSeconds -ge $nextReport) {
                $nextReport = $sw.Elapsed.TotalSeconds + 10
                Write-Host ('    进度 {0}（已用 {1:N1} 分钟）' -f $matches[1], $sw.Elapsed.TotalMinutes)
            }
        }
    }
    return $LASTEXITCODE
}

# ---------------------------------------------------------------- 主流程

$script:ffmpeg = Find-Tool 'ffmpeg'
$script:ffprobe = Find-Tool 'ffprobe'

Write-Info '=========================================='
Write-Info ' 视频音量处理工具'
Write-Info '=========================================='

if (-not $script:ffmpeg -or -not $script:ffprobe) {
    Write-Bad '找不到 ffmpeg / ffprobe。'
    Write-Info '请把 ffmpeg 的 bin 目录放到本工具目录下（本目录\ffmpeg\bin\ffmpeg.exe），或安装到系统 PATH。'
    exit 1
}
Write-Info ('ffmpeg : {0}' -f $script:ffmpeg)

$items = @()
if ($InputPath) {
    $items = @($InputPath)
}
else {
    $items = @($PSScriptRoot)
    Write-Info ''
    Write-Info ('当前文件夹：{0}' -f $PSScriptRoot)
}

if ($Mode -eq 0) {
    Write-Info ''
    Write-Info '选择强度：'
    Write-Info '  1 = 温和（只压最响的，改动最小）'
    Write-Info '  2 = 明显'
    Write-Info '  3 = 强力（推荐，默认）'
    Write-Info '  9 = 只检查，不处理'
    $ans = ''
    for ($i = 0; $i -lt 5; $i++) {
        Write-Host '请输入 1 / 2 / 3 / 9，直接回车 = 3：' -NoNewline
        $a = Read-Host
        if ($null -eq $a) { $a = '' }
        $a = $a.Trim().TrimStart([char]0xFEFF).Trim()
        if ($a -eq '') { $ans = '3'; break }
        if ($a -match '^[1239]') { $ans = $a.Substring(0, 1); break }
        Write-Warn2 '输入无效，请输入 1、2、3、9，或直接回车。'
    }
    if ($ans -eq '') { Write-Bad '多次输入无效，已退出。'; exit 1 }
    $Mode = [int]$ans
}

if ((1, 2, 3, 9) -notcontains $Mode) {
    Write-Bad ('无效的强度选择：{0}' -f $Mode)
    exit 1
}

if ($items.Count -eq 0) {
    Write-Bad '没有指定要处理的文件。'
    exit 1
}

$files = @(Convert-PathList -Items $items -AllowProcessed:($Mode -eq 9))
if ($files.Count -eq 0) {
    Write-Bad '没有找到可处理的视频。'
    exit 1
}

# 过滤掉已经有处理结果的视频
$pending = New-Object 'System.Collections.Generic.List[string]'
$existing = 0
foreach ($f in $files) {
    if ($Mode -eq 9 -or $Overwrite) { $pending.Add($f); continue }
    $bn = [System.IO.Path]::GetFileNameWithoutExtension($f)
    $od = if ($OutDir) { $OutDir } else { Join-Path ([System.IO.Path]::GetDirectoryName($f)) '_处理后' }
    $of = Join-Path $od ($bn + '_音量压缩.mp4')
    if (Test-Path -LiteralPath $of) { $existing++ } else { $pending.Add($f) }
}

Write-Info ''
Write-Info ('找到视频 {0} 个' -f $files.Count)
if ($existing -gt 0) { Write-Warn2 ('  已有处理结果、本次跳过：{0} 个（加 -Overwrite 可重做）' -f $existing) }
if ($Mode -eq 9) { Write-Info '  模式：只检查，不处理' }
else { Write-Info ('  强度：{0}（{1}）' -f $PRESETS["$Mode"].Name, $PRESETS["$Mode"].Filter) }
Write-Info ('  本次处理：{0} 个' -f $pending.Count)
foreach ($f in $pending) { Write-Info ('    ' + [System.IO.Path]::GetFileName($f)) }

if ($pending.Count -eq 0) {
    Write-Info ''
    Write-Ok '没有需要处理的视频。'
    exit 0
}

if (-not $NonInteractive) {
    Write-Info ''
    $ans2 = Read-Host '按回车开始处理，输入 0 取消'
    if ($null -ne $ans2 -and ($ans2.Trim().TrimStart([char]0xFEFF) -match '^0')) {
        Write-Info '已取消，没有改动任何文件。'
        exit 0
    }
}

$files = @($pending)

$summary = New-Object 'System.Collections.Generic.List[object]'
$index = 0

foreach ($file in $files) {
    $index++
    $fileName = [System.IO.Path]::GetFileName($file)
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($file)
    Write-Info ''
    Write-Info ('---------- [{0}/{1}] {2} ----------' -f $index, $files.Count, $fileName)

    $probe = Probe-File $file
    if (-not $probe) {
        Write-Bad '  读不出文件信息，跳过。'
        continue
    }

    $vstream = $probe.streams | Where-Object { $_.codec_type -eq 'video' -and $_.disposition.attached_pic -ne 1 } | Select-Object -First 1
    $astream = $probe.streams | Where-Object { $_.codec_type -eq 'audio' } | Select-Object -First 1

    if (-not $vstream) { Write-Bad '  没有视频流，跳过。'; continue }
    if (-not $astream) { Write-Bad '  没有音频流，跳过。'; continue }

    $srcDur = [double]$probe.format.duration
    Write-Info ('  画面 {0}x{1}  帧率 {2}  时长 {3}' -f $vstream.width, $vstream.height, $vstream.r_frame_rate, (Format-Sec ([int]$srcDur)))

    $reportDir = if ($OutDir) { $OutDir } else { Join-Path ([System.IO.Path]::GetDirectoryName($file)) '_处理后' }
    if (-not (Test-Path -LiteralPath $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }
    $reportFile = Join-Path $reportDir '处理报告.txt'

    $workFile = $file
    $srcLevel = $null
    $usedPreset = '未处理'

    if ($Mode -ne 9) {
        $srcLevel = Get-Level $file
        Write-Info ('  原始电平：平均 {0} / 峰值 {1}' -f (Format-Db $srcLevel.Mean), (Format-Db $srcLevel.Max))

        $outFile = Join-Path $reportDir ($baseName + '_音量压缩.mp4')
        $usedPreset = $PRESETS["$Mode"].Name
        Write-Info '  开始处理……'
        $code = Invoke-Render -File $file -OutFile $outFile -Filter $PRESETS["$Mode"].Filter -Bitrate $AudioBitrate

        if ($code -ne 0 -or -not (Test-Path -LiteralPath $outFile)) {
            Write-Bad ('  处理失败（ffmpeg 返回码 {0}），跳过检查。' -f $code)
            Add-Content -LiteralPath $reportFile -Encoding UTF8 -Value ('{0}  {1}  [{2}]  处理失败（返回码 {3}）' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $fileName, $usedPreset, $code)
            continue
        }
        Write-Ok ('  处理完成：{0}' -f (Split-Path -Leaf $outFile))
        $workFile = $outFile
    }
    else {
        $srcLevel = Get-Level $file
    }

    $problems = New-Object 'System.Collections.Generic.List[string]'
    $warns = New-Object 'System.Collections.Generic.List[string]'
    $outLevel = $null
    $peakText = ''

    if (-not $NoCheck) {
        Write-Info '  检查中……'
        $outLevel = Get-Level $workFile
        Write-Info ('  输出电平：平均 {0} / 峰值 {1}' -f (Format-Db $outLevel.Mean), (Format-Db $outLevel.Max))

        if ($null -eq $outLevel.Mean) { $problems.Add('读不出输出音频电平，可能音频流损坏') }
        if ($outLevel.NaN -and $outLevel.NaN -gt 0) { $problems.Add(('发现 NaN 采样 {0} 个' -f $outLevel.NaN)) }
        if ($outLevel.Inf -and $outLevel.Inf -gt 0) { $problems.Add(('发现 Inf 采样 {0} 个' -f $outLevel.Inf)) }
        if ($outLevel.Max -and $outLevel.Max -gt -0.2) { $warns.Add(('输出峰值 {0}，已经顶到满刻度，可能削波' -f (Format-Db $outLevel.Max))) }

        $errs = @(Get-DecodeErrors $workFile)
        if ($errs.Count -gt 0) { $problems.Add(('解码时报错 {0} 行：{1}' -f $errs.Count, $errs[0])) }

        $tail = Get-TailLevel $workFile 30
        if ($null -ne $tail.Mean -and $tail.Mean -lt -80) { $warns.Add('文件末尾 30 秒几乎没有声音，可能被截断') }

        if ($Mode -ne 9) {
            $oprobe = Probe-File $workFile
            if ($oprobe) {
                $outDur = [double]$oprobe.format.duration
                if ([math]::Abs($outDur - $srcDur) -gt 0.5) {
                    $problems.Add(('时长和源文件不一致：源 {0:N3} 秒 / 输出 {1:N3} 秒' -f $srcDur, $outDur))
                }
                $ovstream = $oprobe.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1
                if ($ovstream -and $vstream.bit_rate -and $ovstream.bit_rate) {
                    $ratio = [double]$ovstream.bit_rate / [double]$vstream.bit_rate
                    if ([math]::Abs($ratio - 1) -gt 0.01) {
                        $problems.Add(('视频被重新编码了：源 {0} / 输出 {1}' -f $vstream.bit_rate, $ovstream.bit_rate))
                    }
                }
            }
        }

        $peaks = @(Get-SecondPeaks $workFile)
        if ($peaks.Count -gt 0) {
            $sorted = @($peaks | Sort-Object)
            $median = $sorted[[int][math]::Floor($sorted.Count / 2)]
            $top = @($peaks | Sort-Object -Descending | Select-Object -First 5)
            $spikes = @()
            for ($i = 0; $i -lt $peaks.Count; $i++) {
                if (($peaks[$i] -gt ($median + 30)) -and ($peaks[$i] -gt -6)) { $spikes += $i }
            }
            if ($spikes.Count -gt 0) {
                $spots = @($spikes | Select-Object -First 5 | ForEach-Object { Format-Sec $_ }) -join '、'
                $warns.Add(('发现 {0} 秒的异常尖峰（远高于整体水平），位置约 {1}' -f $spikes.Count, $spots))
            }
            $topText = @($top | ForEach-Object { '  ' + (Format-Db $_) }) -join ''
            $peakText = ('逐秒峰值：中位 {0}；最响 {1}；最响的 5 秒：{2}' -f (Format-Db $median), (Format-Db $top[0]), (@($top | ForEach-Object { Format-Db $_ }) -join ' / '))
            Write-Info ('  ' + $peakText)
        }
    }

    $verdict = if ($problems.Count -eq 0) { '通过' } else { '发现问题' }
    if ($problems.Count -eq 0) {
        Write-Ok '  检查通过：没有发现技术性异常。'
    }
    else {
        foreach ($p in $problems) { Write-Bad ('  [异常] ' + $p) }
    }
    foreach ($w in $warns) { Write-Warn2 ('  [注意] ' + $w) }

    $line = '{0}  {1}  [{2}]  源 平均 {3}/峰值 {4} → 输出 平均 {5}/峰值 {6}  时长 {7}  结论：{8}' -f `
        (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $fileName, $usedPreset,
        (Format-Db $srcLevel.Mean), (Format-Db $srcLevel.Max),
        (Format-Db $outLevel.Mean), (Format-Db $outLevel.Max),
        (Format-Sec ([int]$srcDur)), $verdict
    Add-Content -LiteralPath $reportFile -Encoding UTF8 -Value $line
    if ($problems.Count -gt 0) {
        foreach ($p in $problems) { Add-Content -LiteralPath $reportFile -Encoding UTF8 -Value ('    异常：' + $p) }
    }
    foreach ($w in $warns) { Add-Content -LiteralPath $reportFile -Encoding UTF8 -Value ('    注意：' + $w) }

    $summary.Add([pscustomobject]@{
        File    = $fileName
        Preset  = $usedPreset
        SrcMean = $srcLevel.Mean
        SrcMax  = $srcLevel.Max
        OutMean = $outLevel.Mean
        OutMax  = $outLevel.Max
        Verdict = $verdict
    })
}

Write-Info ''
Write-Info '=========================================='
Write-Info ' 结果汇总'
Write-Info '=========================================='
foreach ($s in $summary) {
    Write-Host ('{0}  [{1}]  平均 {2} → {3}   峰值 {4} → {5}   {6}' -f `
            $s.File, $s.Preset, (Format-Db $s.SrcMean), (Format-Db $s.OutMean), (Format-Db $s.SrcMax), (Format-Db $s.OutMax), $s.Verdict)
}
Write-Info ''
Write-Info '处理报告已追加写入各输出目录下的「处理报告.txt」。'
