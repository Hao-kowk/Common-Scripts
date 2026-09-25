# -*- coding: utf-8 -*-
"""视频音量处理工具 v1.5（Python 单文件版）

作用：把视频里突然变大的音量段落压下去，其他部分尽量不动。
      视频画面原样复制，只重新编码音频，画质零损失。
      处理完自动做检查，结果写进输出目录的「处理报告.txt」。

用法：把本文件放到放视频的文件夹里，双击运行（或 python 音量处理_v1.5.py）。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

VERSION = "1.5"

# 输出被重定向到文件/管道时用 UTF-8，避免中文乱码（在控制台里保持系统默认，显示更稳）
if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PRESETS = {
    1: ("温和", "acompressor=threshold=-13dB:ratio=5:attack=1:release=250"),
    2: ("明显", "acompressor=threshold=-16dB:ratio=6:attack=1:release=250:detection=peak"),
    3: ("强力", "acompressor=threshold=-18dB:ratio=10:attack=1:release=300"),
    4: ("很强", "acompressor=threshold=-22dB:ratio=14:attack=1:release=300"),
    5: ("最强", "acompressor=threshold=-26dB:ratio=20:attack=1:release=300"),
}
DEFAULT_MODE = 5

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".flv", ".ts", ".avi", ".m4v",
             ".webm", ".wmv", ".mpg", ".mpeg", ".m2ts", ".rmvb"}
REPORT_NAME = "处理报告.txt"


def say(text=""):
    print(text, flush=True)


def find_exe(name):
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "ffmpeg", "bin", name + ".exe"),
        os.path.join(here, name + ".exe"),
        r"C:\Users\Halpc_TUF\Documents\Codex\ffmpeg\ffmpeg-9.0.1-essentials_build\bin\%s.exe" % name,
        r"C:\ffmpeg\bin\%s.exe" % name,
        r"C:\Users\Halpc_TUF\Documents\软件\AsrTools-v1.1.0\%s.exe" % name,
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which(name)


FFMPEG = find_exe("ffmpeg")
FFPROBE = find_exe("ffprobe")


def run(args, **kw):
    """运行外部命令，返回 (returncode, stdout+stderr)。"""
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace", **kw)
    return p.returncode, p.stdout or ""


def fmt_db(v):
    return "%.1f dB" % v if isinstance(v, (int, float)) else "未知"


def fmt_sec(sec):
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def last_number(text, pattern):
    m = re.findall(pattern, text)
    if not m:
        return None
    try:
        return float(m[-1])
    except ValueError:
        return None


def probe(path):
    code, out = run([FFPROBE, "-v", "error", "-print_format", "json",
                     "-show_format", "-show_streams", path])
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def duration_of(path):
    code, out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", path])
    try:
        return float(out.strip().splitlines()[0])
    except Exception:
        return 0.0


def get_level(path, tail_seconds=0):
    args = [FFMPEG, "-hide_banner", "-nostdin"]
    if tail_seconds:
        args += ["-sseof", "-%d" % tail_seconds]
    args += ["-i", path, "-vn", "-af", "astats=metadata=0,volumedetect", "-f", "null", "-"]
    _, out = run(args)
    return {
        "mean": last_number(out, r"mean_volume:\s*(-?[\d.]+)"),
        "max": last_number(out, r"max_volume:\s*(-?[\d.]+)"),
        "nan": last_number(out, r"Number of NaNs:\s*(-?[\d.]+)"),
        "inf": last_number(out, r"Number of Infs:\s*(-?[\d.]+)"),
    }


def decode_errors(path):
    _, out = run([FFMPEG, "-v", "error", "-nostdin", "-i", path, "-vn", "-f", "null", "-"])
    return [ln for ln in out.splitlines() if ln.strip()]


def second_peaks(path):
    """逐秒峰值（dB），用于找异常尖峰。"""
    tmpdir = tempfile.gettempdir()
    name = "peaks_%d.txt" % int(time.time() * 1000 % 10 ** 9)
    filt = ("asetnsamples=n=48000,astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=%s" % name)
    run([FFMPEG, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", filt,
         "-f", "null", "-"], cwd=tmpdir)
    vals = []
    p = os.path.join(tmpdir, name)
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                i = line.find("Peak_level=")
                if i >= 0:
                    x = line[i + 11:].strip()
                    try:
                        vals.append(float(x))
                    except ValueError:
                        vals.append(-200.0)
        try:
            os.remove(p)
        except OSError:
            pass
    return vals


def render(src, out, filt, bitrate):
    args = [FFMPEG, "-hide_banner", "-nostdin", "-i", src,
            "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
            "-af", filt, "-c:a", "aac", "-b:a", "%dk" % bitrate, "-y", out]
    t0 = time.time()
    next_report = 0.0
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
    for line in p.stdout:
        m = re.search(r"time=(\d+:\d+:\d+)", line)
        if m:
            now = time.time() - t0
            if now >= next_report:
                next_report = now + 10
                say("    进度 %s（已用 %.1f 分钟）" % (m.group(1), now / 60.0))
    p.wait()
    return p.returncode


def collect_videos(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith("_")]
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in VIDEO_EXT and not os.path.splitext(fn)[0].endswith("_音量压缩"):
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def ask(prompt, pattern, default, bad):
    for _ in range(5):
        try:
            a = input(prompt).strip().lstrip("\ufeff").strip()
        except EOFError:
            a = ""
        if a == "" and default:
            return default
        if re.match(pattern, a):
            return a
        say(bad)
    return None


def main():
    say("=" * 42)
    say(" 视频音量处理工具  v%s" % VERSION)
    say("=" * 42)
    if not FFMPEG or not FFPROBE:
        say("找不到 ffmpeg / ffprobe，无法处理。")
        return 1
    say("ffmpeg : %s" % FFMPEG)

    root = os.path.dirname(os.path.abspath(__file__))
    extra = [a for a in sys.argv[1:] if not a.startswith("-")]
    if extra:
        root = os.path.abspath(extra[0].strip().strip('"'))
    if os.path.isfile(root):
        root = os.path.dirname(root)
    say("")
    say("当前文件夹：%s" % root)

    mode = None
    say("")
    say("选择压缩强度（数字越大，大声的部分压得越低）：")
    say("  1 = 温和    只压最响的，改动最小")
    say("  2 = 明显")
    say("  3 = 强力    大声处约压到 -16 dB")
    say("  4 = 很强    大声处约压到 -20 dB")
    say("  5 = 最强    推荐，直接回车就是它，大声处约压到 -25 dB")
    say("  9 = 只检查，不处理")
    a = ask("请输入 1 / 2 / 3 / 4 / 5 / 9，直接回车 = %d：" % DEFAULT_MODE,
            r"^[123459]", str(DEFAULT_MODE), "输入无效，请输入 1、2、3、4、5、9，或直接回车。")
    if a is None:
        say("多次输入无效，已退出。")
        return 1
    mode = int(a[0])

    videos = collect_videos(root)
    say("")
    say("找到视频 %d 个" % len(videos))
    if not videos:
        say("没有找到视频文件。")
        return 1

    pending, existing = [], 0
    for v in videos:
        if mode == 9:
            pending.append(v)
            continue
        base = os.path.splitext(os.path.basename(v))[0]
        outdir = os.path.join(os.path.dirname(v), "_处理后")
        if os.path.exists(os.path.join(outdir, base + "_音量压缩.mp4")) or \
           os.path.exists(os.path.join(outdir, base + ".mp4")):
            existing += 1
        else:
            pending.append(v)

    if existing:
        say("  已有处理结果、本次跳过：%d 个" % existing)
    if mode == 9:
        say("  模式：只检查，不处理")
    else:
        say("  强度：%s（%s）" % (PRESETS[mode][0], PRESETS[mode][1]))
    say("  本次处理：%d 个" % len(pending))
    for v in pending:
        say("    " + os.path.basename(v))
    if not pending:
        say("")
        say("没有需要处理的视频。")
        return 0

    say("")
    try:
        ans = input("按回车开始处理，输入 0 取消").strip().lstrip("\ufeff")
    except EOFError:
        ans = ""
    if ans.startswith("0"):
        say("已取消，没有改动任何文件。")
        return 0

    summary = []
    for idx, src in enumerate(pending, 1):
        name = os.path.basename(src)
        base = os.path.splitext(name)[0]
        say("")
        say("---------- [%d/%d] %s ----------" % (idx, len(pending), name))

        info = probe(src)
        if not info:
            say("  读不出文件信息，跳过。")
            continue
        vstream = next((s for s in info["streams"]
                        if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
        astream = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
        if not vstream:
            say("  没有视频流，跳过。")
            continue
        if not astream:
            say("  没有音频流，跳过。")
            continue

        src_dur = float(info["format"].get("duration", 0) or 0)
        say("  画面 %sx%s  时长 %s" % (vstream.get("width"), vstream.get("height"), fmt_sec(src_dur)))

        outdir = os.path.join(os.path.dirname(src), "_处理后")
        os.makedirs(outdir, exist_ok=True)
        report = os.path.join(outdir, REPORT_NAME)
        work = src
        src_level = None
        preset_name = "未处理"

        if mode != 9:
            src_level = get_level(src)
            say("  原始电平：平均 %s / 峰值 %s" % (fmt_db(src_level["mean"]), fmt_db(src_level["max"])))
            out_file = os.path.join(outdir, base + "_音量压缩.mp4")
            preset_name = PRESETS[mode][0]
            say("  开始处理……")
            code = render(src, out_file, PRESETS[mode][1], 192)
            if code != 0 or not os.path.isfile(out_file):
                say("  处理失败（ffmpeg 返回码 %s），跳过检查。" % code)
                with open(report, "a", encoding="utf-8") as f:
                    f.write("%s  %s  [%s]  处理失败（返回码 %s）\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), name, preset_name, code))
                continue
            say("  处理完成：%s" % os.path.basename(out_file))
            work = out_file
        else:
            src_level = get_level(src)

        problems, warns = [], []
        say("  检查中……")
        lvl = get_level(work)
        say("  输出电平：平均 %s / 峰值 %s" % (fmt_db(lvl["mean"]), fmt_db(lvl["max"])))
        if lvl["mean"] is None:
            problems.append("读不出输出音频电平，可能音频流损坏")
        if lvl["nan"]:
            problems.append("发现 NaN 采样 %d 个" % lvl["nan"])
        if lvl["inf"]:
            problems.append("发现 Inf 采样 %d 个" % lvl["inf"])
        if lvl["max"] is not None and lvl["max"] > -0.2:
            warns.append("输出峰值 %s，已经顶到满刻度，可能削波" % fmt_db(lvl["max"]))

        errs = decode_errors(work)
        if errs:
            problems.append("解码时报错 %d 行：%s" % (len(errs), errs[0]))

        tail = get_level(work, tail_seconds=30)
        if tail["mean"] is not None and tail["mean"] < -80:
            warns.append("文件末尾 30 秒几乎没有声音，可能被截断")

        if mode != 9:
            oinfo = probe(work)
            if oinfo:
                out_dur = float(oinfo["format"].get("duration", 0) or 0)
                if abs(out_dur - src_dur) > 0.5:
                    problems.append("时长和源文件不一致：源 %.3f 秒 / 输出 %.3f 秒" % (src_dur, out_dur))
                ov = next((s for s in oinfo["streams"] if s.get("codec_type") == "video"), None)
                sb, ob = vstream.get("bit_rate"), (ov or {}).get("bit_rate")
                if sb and ob:
                    try:
                        ratio = float(ob) / float(sb)
                        if abs(ratio - 1) > 0.01:
                            problems.append("视频被重新编码了：源 %s / 输出 %s" % (sb, ob))
                    except Exception:
                        pass

        peaks = second_peaks(work)
        if peaks:
            s = sorted(peaks)
            median = s[len(s) // 2]
            top = sorted(peaks, reverse=True)[:5]
            spikes = [i for i, v in enumerate(peaks) if v > median + 30 and v > -6]
            if spikes:
                spots = "、".join(fmt_sec(i) for i in spikes[:5])
                warns.append("发现 %d 秒的异常尖峰（远高于整体水平），位置约 %s" % (len(spikes), spots))
            say("  逐秒峰值：中位 %s；最响 %s；最响的 5 秒：%s"
                % (fmt_db(median), fmt_db(top[0]), " / ".join(fmt_db(x) for x in top)))

        verdict = "通过" if not problems else "发现问题"
        if not problems:
            say("  检查通过：没有发现技术性异常。")
        else:
            for x in problems:
                say("  [异常] " + x)
        for x in warns:
            say("  [注意] " + x)

        line = ("%s  %s  [%s]  源 平均 %s/峰值 %s → 输出 平均 %s/峰值 %s  时长 %s  结论：%s  (v%s)"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), name, preset_name,
                   fmt_db(src_level["mean"]), fmt_db(src_level["max"]),
                   fmt_db(lvl["mean"]), fmt_db(lvl["max"]), fmt_sec(src_dur), verdict, VERSION))
        with open(report, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            for x in problems:
                f.write("    异常：" + x + "\n")
            for x in warns:
                f.write("    注意：" + x + "\n")

        summary.append((name, preset_name, src_level["mean"], lvl["mean"],
                        src_level["max"], lvl["max"], verdict))

    say("")
    say("=" * 42)
    say(" 结果汇总")
    say("=" * 42)
    for r in summary:
        say("%s  [%s]  平均 %s → %s   峰值 %s → %s   %s"
            % (r[0], r[1], fmt_db(r[2]), fmt_db(r[3]), fmt_db(r[4]), fmt_db(r[5]), r[6]))
    say("")
    say("处理报告已写入各输出目录下的「%s」。" % REPORT_NAME)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        say("")
        say("已中断。")
        code = 130
    if sys.stdout.isatty():
        try:
            input("按回车退出……")
        except EOFError:
            pass
    sys.exit(code)
