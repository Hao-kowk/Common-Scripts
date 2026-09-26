# -*- coding: utf-8 -*-
"""YouTube 下载 v1.0

做的事：先「整段下」，再「本地切」。

    为什么这么绕？因为「只下一段」反而更慢。
    分段下载只能走 ffmpeg 单连接顺序抓，实测只有 0.5 MiB/s 左右；
    整段下载开 8 条连接能跑到 9 MiB/s 以上。所以哪怕你只要后 3 小时，
    整段下完再本地切，也比只下那 3 小时快好几倍。
    （本地切是 -c copy 直接复制，不重编码，画质一点不损失。）

    流程：
        1. yt-dlp + aria2c（8 连接）把画面和声音分别下下来，支持断点续传
        2. ffmpeg 无损合并成一个 mp4
        3. 如果指定了区间，再从合并好的文件里切出那一段
        4. ffprobe 检查成品时长和音画起始时间，确认没跑偏

用法：
    双击本文件 → 按提示粘链接，再按提示决定要不要只留一段

    命令行：
        python YouTube下载_v1.0.py <链接>
        python YouTube下载_v1.0.py <链接> --last 3           只要最后 3 小时
        python YouTube下载_v1.0.py <链接> --section 1:30-2:45 只要 1:30 到 2:45
        python YouTube下载_v1.0.py <链接> --audio-only        只要音频
        python YouTube下载_v1.0.py <链接> --quality 720       720p
        python YouTube下载_v1.0.py <链接> --cleanup           切完删掉中间文件

    时间写法：带冒号的按 时:分:秒 解析（1:30 = 1 分 30 秒，1:30:00 = 1.5 小时）；
              不带冒号的数字 = 小时（--last 3 就是 3 小时）。

    成品在脚本目录的 _下载\\ 里。中途断了直接重跑，会从断点继续。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.0"

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE / "bin"
DEFAULT_OUTDIR = HERE / "_下载"

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
ARIA_URL = ("https://github.com/aria2/aria2/releases/download/release-1.37.0/"
            "aria2-1.37.0-win-64bit-build1.zip")

# 代理：默认用 Clash 的本地端口；留空则自动读系统代理
DEFAULT_PROXY = "http://127.0.0.1:7897"

ARIA_CONNECTIONS = 8

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def say(text=""):
    print(text, flush=True)


def human(nbytes):
    try:
        nbytes = float(nbytes)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024 or unit == "TB":
            return "%.2f %s" % (nbytes, unit)
        nbytes /= 1024.0


def hms(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s)


# --------------------------------------------------------------------------
# 找工具 / 自动补工具
# --------------------------------------------------------------------------

def find_exe(name):
    """按顺序找可执行文件，找不到返回 None"""
    exe = name + ".exe"
    candidates = [
        BIN_DIR / exe,
        HERE / exe,
        HERE / name / "bin" / exe,
        HERE / "ffmpeg" / "bin" / exe,
        Path(r"C:\Users\Halpc_TUF\Documents\Codex\ffmpeg\ffmpeg-9.0.1-essentials_build\bin") / exe,
        Path(r"C:\ffmpeg\bin") / exe,
        Path(r"C:\Users\Halpc_TUF\Documents\软件\AsrTools-v1.1.0") / exe,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which(name) or shutil.which(exe)


def download_file(url, dest: Path):
    say("   下载 %s" % url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)
    say("   完成：%s（%s）" % (dest.name, human(dest.stat().st_size)))


def ensure_ytdlp():
    exe = find_exe("yt-dlp")
    if exe:
        return exe
    say("[*] 没找到 yt-dlp，自动下载到 bin\\ ...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    download_file(YTDLP_URL, BIN_DIR / "yt-dlp.exe")
    return str(BIN_DIR / "yt-dlp.exe")


def ensure_aria2():
    exe = find_exe("aria2c")
    if exe:
        return exe
    say("[*] 没找到 aria2c（多线程下载用），自动下载 ...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = BIN_DIR / "aria2.zip"
    download_file(ARIA_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.lower().endswith("aria2c.exe"):
                with zf.open(member) as src, open(BIN_DIR / "aria2c.exe", "wb") as dst:
                    shutil.copyfileobj(src, dst)
                break
    zip_path.unlink(missing_ok=True)
    return str(BIN_DIR / "aria2c.exe")


def ensure_ffmpeg():
    ffmpeg = find_exe("ffmpeg")
    ffprobe = find_exe("ffprobe")
    if not ffmpeg or not ffprobe:
        say("!! 没找到 ffmpeg / ffprobe。")
        say("   下载 https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
        say("   解压后把 bin 文件夹改名为 ffmpeg 放在脚本旁边，或放进 PATH。")
        raise SystemExit(1)
    return ffmpeg, ffprobe


# --------------------------------------------------------------------------
# 代理
# --------------------------------------------------------------------------

def detect_proxy():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = winreg.QueryValueEx(key, "ProxyServer")[0]
        finally:
            winreg.CloseKey(key)
        if enabled and server:
            if "=" in server:
                for part in server.split(";"):
                    if part.lower().startswith("http="):
                        server = part.split("=", 1)[1]
                        break
            if not server.startswith("http"):
                server = "http://" + server
            return server
    except Exception:
        pass
    return None


def resolve_proxy(value):
    if value is None:
        return DEFAULT_PROXY
    if value.lower() in ("none", "off", "-", ""):
        return None
    if value.lower() == "auto":
        return detect_proxy()
    return value


# --------------------------------------------------------------------------
# 跑外部命令
# --------------------------------------------------------------------------

def run_stream(cmd):
    """行缓冲地跑，实时把输出打出来（yt-dlp 用）"""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            say("   " + line)
    proc.wait()
    return proc.returncode


def run_inherit(cmd):
    """直接继承控制台，ffmpeg 的进度条才能动"""
    say("   " + " ".join('"%s"' % c if " " in str(c) else str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd])


# --------------------------------------------------------------------------
# 时间参数
# --------------------------------------------------------------------------

def parse_time(text):
    """不带冒号的数字 = 小时；带冒号按 时:分:秒 / 分:秒"""
    text = str(text).strip()
    if not text:
        return None
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        raise ValueError("看不懂的时间：%s" % text)
    return float(text) * 3600.0


def parse_section(text, duration):
    """返回 (start, end)；text 形如 '1:30-2:45'"""
    text = str(text).strip()
    if "-" not in text:
        raise ValueError("区间要写成 起点-终点，例如 1:30-2:45")
    left, right = text.split("-", 1)
    start = parse_time(left) or 0.0
    end = parse_time(right)
    if end is None or end <= 0:
        end = duration
    if end <= start:
        raise ValueError("终点比起点还早")
    return start, min(end, duration)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def probe(yt, url, proxy, cookies, ffmpeg_dir):
    cmd = [yt, "-J", "--no-warnings", "--socket-timeout", "30",
           "--ffmpeg-location", ffmpeg_dir]
    if proxy:
        cmd += ["--proxy", proxy]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd.append(url)
    out = subprocess.run([str(c) for c in cmd], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0 or not out.stdout.strip():
        say("!! 取视频信息失败：")
        say((out.stderr or out.stdout or "").strip()[-1500:])
        raise SystemExit(1)
    info = json.loads(out.stdout)
    return {
        "id": info.get("id") or "video",
        "title": info.get("title") or "video",
        "duration": float(info.get("duration") or 0),
    }


def build_video_selector(quality):
    if quality in (None, "best"):
        return ("bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b",
                "bv*[vcodec^=avc1]/bv*",
                "ba[acodec^=mp4a]/ba")
    h = int(quality)
    return (
        "bv*[vcodec^=avc1][height<=%d]+ba[acodec^=mp4a]/bv*[height<=%d]+ba/b" % (h, h),
        "bv*[vcodec^=avc1][height<=%d]/bv*[height<=%d]" % (h, h),
        "ba[acodec^=mp4a]/ba",
    )


def ytdlp_base(yt, proxy, ffmpeg_dir, aria=None, cookies=None):
    cmd = [yt, "--no-warnings", "--newline", "--continue",
           "--retries", "100", "--fragment-retries", "100",
           "--file-access-retries", "50", "--socket-timeout", "60",
           "--ffmpeg-location", str(ffmpeg_dir), "--no-mtime"]
    if proxy:
        cmd += ["--proxy", proxy]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    if aria:
        cmd += [
            "--downloader", str(aria),
            "--downloader-args",
            "aria2c:-x%d -s%d -k1M --max-tries=50 --retry-wait=10 "
            "--continue=true --file-allocation=none --summary-interval=30 "
            "--disable-ipv6=true" % (ARIA_CONNECTIONS, ARIA_CONNECTIONS),
        ]
    return cmd


def verify_output(ffprobe, path: Path):
    """看成品时长和音画起始时间差"""
    def stream_info(kind):
        cmd = [ffprobe, "-v", "error", "-select_streams", kind,
               "-show_entries", "stream=start_time,duration",
               "-of", "json", str(path)]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            data = json.loads(out.stdout or "{}")
            streams = data.get("streams") or [{}]
            st = streams[0]
            return (float(st.get("start_time") or 0.0),
                    float(st.get("duration") or 0.0))
        except Exception:
            return (None, None)

    v_start, v_dur = stream_info("v:0")
    a_start, a_dur = stream_info("a:0")
    say("   画面起始 %s，时长 %s" % (
        "%.3fs" % v_start if v_start is not None else "?",
        hms(v_dur) if v_dur else "?"))
    say("   声音起始 %s，时长 %s" % (
        "%.3fs" % a_start if a_start is not None else "?",
        hms(a_dur) if a_dur else "?"))
    if v_start is not None and a_start is not None and abs(v_start - a_start) > 0.3:
        say("   !! 音画起始差了 %.3f 秒，留意一下" % abs(v_start - a_start))
    else:
        say("   音画起点对齐，没问题")
    return v_dur or a_dur or 0.0


def safe_name(text):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    return text.strip(" .") or "video"


def process_one(url, args, tools, proxy, outdir):
    yt, aria, ffmpeg, ffprobe = tools
    ffmpeg_dir = str(Path(ffmpeg).parent)

    say("=" * 52)
    say(" 处理：%s" % url)
    say("=" * 52)
    say("[1/5] 读取视频信息 ...")
    info = probe(yt, url, proxy, args.cookies, ffmpeg_dir)
    title = info["title"]
    duration = info["duration"]
    say("   标题：%s" % title)
    say("   时长：%s（%d 秒）" % (hms(duration), duration))

    selection = args.selection        # (start, end) 或 None
    if selection and duration and selection[1] > duration:
        selection = (selection[0], duration)

    workdir = outdir / ("_tmp_" + safe_name(info["id"]))
    workdir.mkdir(parents=True, exist_ok=True)

    base = ytdlp_base(yt, proxy, ffmpeg_dir, aria, args.cookies)
    vfull, vonly, aonly = build_video_selector(args.quality)

    video_file = None
    if not args.audio_only:
        say("[2/5] 下载画面（%d 条连接，可断点续传）..." % ARIA_CONNECTIONS)
        cmd = base + ["-f", vonly, "-o", str(workdir / "video.%(ext)s"), url]
        if run_stream(cmd) != 0:
            say("!! 画面下载失败。修好网络后重跑本脚本即可续传。")
            raise SystemExit(1)
        got = [p for p in sorted(workdir.glob("video.*"))
               if p.suffix not in (".part", ".aria2")]
        if not got:
            say("!! 没找到下载好的画面文件")
            raise SystemExit(1)
        video_file = got[0]
        say("   画面：%s（%s）" % (video_file.name, human(video_file.stat().st_size)))
    else:
        say("[2/5] 跳过画面（--audio-only）")

    say("[3/5] 下载声音 ...")
    cmd = base + ["-f", aonly, "-o", str(workdir / "audio.%(ext)s"), url]
    if run_stream(cmd) != 0:
        say("!! 声音下载失败。修好网络后重跑本脚本即可续传。")
        raise SystemExit(1)
    got = [p for p in sorted(workdir.glob("audio.*"))
           if p.suffix not in (".part", ".aria2")]
    if not got:
        say("!! 没找到下载好的声音文件")
        raise SystemExit(1)
    audio_file = got[0]
    say("   声音：%s（%s）" % (audio_file.name, human(audio_file.stat().st_size)))

    tag = ""
    if selection:
        tag = "_%s-%s" % (hms(selection[0]).replace(":", "."),
                          hms(selection[1]).replace(":", "."))
    final = outdir / (safe_name(title) + tag + ".mp4")
    if final.exists() and not args.overwrite:
        say("   成品已存在，跳过：%s（加 --overwrite 可覆盖）" % final.name)
        return final

    merged = workdir / "merged.mp4"
    if video_file is None:
        say("[4/5] 只下音频，直接用声音文件")
        merged = audio_file
    elif merged.exists() and merged.stat().st_size > 0:
        say("[4/5] 合并画面和声音（上次已合过，跳过）")
    else:
        say("[4/5] 合并画面和声音（-c copy，不重编码）...")
        cmd = [ffmpeg, "-y", "-i", str(video_file), "-i", str(audio_file),
               "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(merged)]
        if run_inherit(cmd) != 0:
            say("!! 合并失败")
            raise SystemExit(1)
        say("   合并完成：%s" % human(merged.stat().st_size))

    if selection:
        start, end = selection
        say("[5/5] 切出 %s ~ %s（本地切，不重编码）..." % (hms(start), hms(end)))
        cmd = [ffmpeg, "-y",
               "-ss", "%.3f" % start, "-t", "%.3f" % (end - start),
               "-i", str(merged), "-map", "0", "-c", "copy",
               "-avoid_negative_ts", "make_zero",
               "-movflags", "+faststart", str(final)]
        if run_inherit(cmd) != 0:
            say("!! 切片失败")
            raise SystemExit(1)
    else:
        say("[5/5] 不需要切片，直接收尾 ...")
        if merged != final:
            shutil.copy2(merged, final)

    say("")
    say("成品：%s（%s）" % (final, human(final.stat().st_size)))
    verify_output(ffprobe, final)

    if args.cleanup:
        say("清理中间文件 ...")
        shutil.rmtree(workdir, ignore_errors=True)
        say("   已删除 %s" % workdir)
    else:
        total = sum(p.stat().st_size for p in workdir.glob("*") if p.is_file())
        say("   中间文件留在 %s（%s），想省空间可以加 --cleanup" % (workdir, human(total)))

    say("")
    return final


def ask_inputs(args, yt, proxy, ffmpeg_dir, cookies):
    """双击模式：交互着问"""
    say("=" * 52)
    say(" YouTube 下载  v%s" % VERSION)
    say("=" * 52)
    say("把视频链接粘进来，多个链接一行一个，粘完再按一次回车：")
    urls = []
    while True:
        line = input("> ").strip()
        if not line:
            if urls:
                break
            continue
        urls.append(line)

    say("")
    say("[*] 读取第一个视频的信息 ...")
    info = probe(yt, urls[0], proxy, cookies, ffmpeg_dir)
    say("   标题：%s" % info["title"])
    say("   时长：%s" % hms(info["duration"]))
    say("")
    say("要只保留一段吗？")
    say("   直接回车   = 整段都要")
    say("   输入 3     = 只要最后 3 小时")
    say("   输入 1:30-2:45 = 只要 1 分 30 秒到 2 分 45 秒（要小时就写 1:30:00）")
    answer = input("> ").strip()
    if answer:
        if re.fullmatch(r"[\d.]+", answer):
            hours = float(answer)
            start = max(0.0, info["duration"] - hours * 3600.0)
            args.selection = (start, info["duration"])
        else:
            try:
                args.selection = parse_section(answer, info["duration"])
            except ValueError as exc:
                say("!! %s" % exc)
                say("   当作整段处理。")
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="YouTube 下载 v%s（先整段下，再本地切）" % VERSION)
    parser.add_argument("urls", nargs="*", help="视频链接；双击时不填")
    parser.add_argument("--last", type=str, default=None,
                        help="只要最后 N 小时，例如 --last 3")
    parser.add_argument("--section", type=str, default=None,
                        help="只要某一段，例如 --section 1:30-2:45")
    parser.add_argument("--quality", default="1080",
                        help="最高画质，默认 1080；可写 720 / 480 / best")
    parser.add_argument("--audio-only", action="store_true", help="只下音频")
    parser.add_argument("--outdir", default=None, help="成品目录，默认脚本目录的 _下载\\")
    parser.add_argument("--proxy", default=None,
                        help="代理地址，默认 %s；写 none 表示不用代理，写 auto 自动读系统代理" % DEFAULT_PROXY)
    parser.add_argument("--cookies", default=None,
                        help="需要登录才能看的视频，写浏览器名，例如 edge")
    parser.add_argument("--cleanup", action="store_true",
                        help="切完之后删掉中间文件（整段 mp4 和分离的音视频轨）")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的成品")
    args = parser.parse_args()

    proxy = resolve_proxy(args.proxy)
    if proxy:
        say("[*] 代理：%s" % proxy)
    else:
        say("[*] 代理：不使用")

    yt = ensure_ytdlp()
    aria = ensure_aria2()
    ffmpeg, ffprobe = ensure_ffmpeg()
    tools = (yt, aria, ffmpeg, ffprobe)

    outdir = Path(args.outdir).expanduser().resolve() if args.outdir else DEFAULT_OUTDIR
    outdir.mkdir(parents=True, exist_ok=True)

    interactive = not args.urls
    if interactive:
        urls = ask_inputs(args, yt, proxy, str(Path(ffmpeg).parent), args.cookies)
    else:
        urls = list(args.urls)
        duration_probe = probe(yt, urls[0], proxy, args.cookies, str(Path(ffmpeg).parent))
        if args.last:
            hours = float(args.last)
            start = max(0.0, duration_probe["duration"] - hours * 3600.0)
            args.selection = (start, duration_probe["duration"])
        elif args.section:
            args.selection = parse_section(args.section, duration_probe["duration"])
        else:
            args.selection = None

    started = time.time()
    outputs = []
    for url in urls:
        outputs.append(process_one(url, args, tools, proxy, outdir))

    say("=" * 52)
    say(" 全部完成，用了 %s" % hms(time.time() - started))
    for path in outputs:
        if path and Path(path).exists():
            say("   %s" % path)
    say("=" * 52)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("")
        say("已取消。下次重跑会从断点继续。")
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("按回车退出 ...")
    except Exception:
        pass
