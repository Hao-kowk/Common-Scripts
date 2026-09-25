# -*- coding: utf-8 -*-
# 批量转字幕：用 B 站必剪（Bcut）语音识别接口，把视频转成外挂 .srt 字幕
#
# 用法示例：
#   python bcut_transcribe.py                    处理脚本所在文件夹里的所有视频
#   python bcut_transcribe.py "D:\某个文件夹"     处理指定文件夹
#   python bcut_transcribe.py a.mp4 b.mp4        处理指定文件
#   python bcut_transcribe.py --chunk 600 --overwrite
#
# 接口流程（与 AsrTools / VideoCaptioner 的 BcutASR 一致）：
#   resource/create -> 分片 PUT -> resource/create/complete -> task -> task/result

from __future__ import annotations

import argparse
import http.cookiejar
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE_URL = "https://member.bilibili.com/x/bcut/rubick-interface"
API_REQ_UPLOAD = API_BASE_URL + "/resource/create"
API_COMMIT_UPLOAD = API_BASE_URL + "/resource/create/complete"
API_CREATE_TASK = API_BASE_URL + "/task"
API_QUERY_RESULT = API_BASE_URL + "/task/result"

HEADERS = {
    "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
    "Content-Type": "application/json",
}
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".flv", ".ts", ".avi", ".m4v", ".webm",
             ".wmv", ".mpg", ".mpeg", ".m2ts", ".rmvb"}

RETRYABLE_STATUS = {408, 409, 412, 425, 429, 500, 502, 503, 504}

PRE_POLL_DELAY = 8
POLL_INTERVAL = 5
BLOCKED_WAIT = 30
POLL_DEADLINE = 1800
MAX_RETRIES = 6

COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))
_warmed_up = False


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def find_exe(name):
    from shutil import which
    here = Path(__file__).resolve().parent
    candidates = [
        here / "ffmpeg" / "bin" / (name + ".exe"),
        here / (name + ".exe"),
        Path(r"C:\Users\Halpc_TUF\Documents\Codex\ffmpeg\ffmpeg-9.0.1-essentials_build\bin") / (name + ".exe"),
        Path(r"C:\ffmpeg\bin") / (name + ".exe"),
        Path(r"C:\Users\Halpc_TUF\Documents\软件\AsrTools-v1.1.0") / (name + ".exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return which(name)


FFMPEG = find_exe("ffmpeg")
FFPROBE = find_exe("ffprobe")


def warm_up():
    global _warmed_up
    if _warmed_up:
        return
    try:
        req = urllib.request.Request("https://www.bilibili.com/",
                                     headers={"User-Agent": BROWSER_UA})
        with OPENER.open(req, timeout=20) as resp:
            resp.read(2048)
        names = sorted(c.name for c in COOKIE_JAR)
        log("接口预热完成：%s" % (", ".join(names) if names else "无 cookie"))
    except Exception as exc:
        log("接口预热失败（继续尝试）：%s" % exc)
    _warmed_up = True


def request(method, url, data=None, headers=None, retries=MAX_RETRIES, timeout=120):
    warm_up()
    last_exc = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        for key, value in (headers or HEADERS).items():
            req.add_header(key, value)
        try:
            with OPENER.open(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in RETRYABLE_STATUS or attempt >= retries:
                raise
            wait = min(60, (2 ** attempt) + random.random() * 2)
            log("HTTP %s，%.0f 秒后重试（%d/%d）" % (exc.code, wait, attempt + 1, retries))
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            wait = min(60, (2 ** attempt) + random.random() * 2)
            log("网络异常（%s），%.0f 秒后重试（%d/%d）" % (exc, wait, attempt + 1, retries))
            time.sleep(wait)
    raise RuntimeError("请求失败：%s" % last_exc)


def media_duration(path):
    if not FFPROBE:
        return 0.0
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def extract_chunk(src, start, duration, out):
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-fflags", "+genpts",
        "-ss", "%.3f" % start, "-t", "%.3f" % duration, "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000",
        "-af", "aresample=async=1:first_pts=0",
        "-b:a", "64k", "-f", "mp3", str(out),
    ]
    subprocess.run(cmd, check=True)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("音频抽取失败（输出为空）")


def transcribe_chunk(chunk_path):
    file_bytes = chunk_path.read_bytes()
    size = len(file_bytes)

    payload = json.dumps({
        "type": 2,
        "name": "audio.mp3",
        "size": size,
        "ResourceFileType": "mp3",
        "model_id": "8",
    }).encode()
    body, _ = request("POST", API_REQ_UPLOAD, data=payload)
    data = json.loads(body)["data"]
    upload_urls = data["upload_urls"]
    per_size = data["per_size"]

    etags = []
    for idx, upload_url in enumerate(upload_urls):
        part = file_bytes[idx * per_size:(idx + 1) * per_size]
        _, headers = request("PUT", upload_url, data=part)
        etag = headers.get("Etag") or headers.get("etag")
        if etag:
            etags.append(etag)

    commit = json.dumps({
        "InBossKey": data["in_boss_key"],
        "ResourceId": data["resource_id"],
        "Etags": ",".join(etags),
        "UploadId": data["upload_id"],
        "model_id": "8",
    }).encode()
    body, _ = request("POST", API_COMMIT_UPLOAD, data=commit)
    download_url = json.loads(body)["data"]["download_url"]

    task_body = json.dumps({"resource": download_url, "model_id": "8"}).encode()
    body, _ = request("POST", API_CREATE_TASK, data=task_body)
    task_id = json.loads(body)["data"]["task_id"]

    query = urllib.parse.urlencode({"model_id": 7, "task_id": task_id})
    result_url = "%s?%s" % (API_QUERY_RESULT, query)
    time.sleep(PRE_POLL_DELAY)
    deadline = time.time() + POLL_DEADLINE
    blocked = 0
    while time.time() < deadline:
        try:
            body, _ = request("GET", result_url, retries=0)
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                blocked += 1
                log("接口限流（412），等待 %d 秒（第 %d 次）" % (BLOCKED_WAIT, blocked))
                time.sleep(BLOCKED_WAIT)
                continue
            raise
        task = json.loads(body)["data"]
        state = task.get("state")
        if state == 4:
            result = json.loads(task["result"])
            return result.get("utterances", [])
        if state not in (0, 1, 2, 3):
            raise RuntimeError("任务返回异常状态 %s：%s" % (state, task))
        time.sleep(POLL_INTERVAL)
    raise RuntimeError("识别超时")


def format_time(ms):
    ms = max(0, int(ms))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, ms)


def merge_segments(items, max_len=22, max_dur=8000, max_gap=1200):
    out = []
    for it in items:
        text = (it.get("transcript") or "").strip()
        if not text:
            continue
        cur = {"transcript": text, "start_time": it["start_time"], "end_time": it["end_time"]}
        if out:
            last = out[-1]
            merged_len = len(last["transcript"]) + len(cur["transcript"])
            merged_dur = cur["end_time"] - last["start_time"]
            gap = cur["start_time"] - last["end_time"]
            if (merged_len <= max_len and merged_dur <= max_dur and gap <= max_gap
                    and not last["transcript"].endswith(("。", "！", "？", "!", "?"))):
                last["transcript"] += cur["transcript"]
                last["end_time"] = cur["end_time"]
                continue
        out.append(cur)
    return out


def utterances_to_srt(items):
    lines = []
    idx = 0
    for it in items:
        text = (it.get("transcript") or "").strip()
        if not text:
            continue
        idx += 1
        lines.append(str(idx))
        lines.append("%s --> %s" % (format_time(it["start_time"]), format_time(it["end_time"])))
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def collect_videos(paths, default_dir):
    targets = paths if paths else [str(default_dir)]
    found = []
    for t in targets:
        p = Path(str(t).strip().strip('"'))
        if not p.exists():
            log("路径不存在，跳过：%s" % p)
            continue
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.suffix.lower() in VIDEO_EXT:
                    found.append(f)
        elif p.suffix.lower() in VIDEO_EXT:
            found.append(p)
    uniq = []
    for f in found:
        if f not in uniq:
            uniq.append(f)
    return uniq


def transcribe_video(video, args):
    cache_path = video.with_suffix(video.suffix + ".asr_cache.json")
    srt_path = video.with_suffix(".srt")

    if srt_path.exists() and not args.overwrite:
        log("已存在字幕，跳过：%s（加 --overwrite 可覆盖）" % srt_path.name)
        return 0

    dur = media_duration(video)
    if dur <= 0:
        log("读不出视频时长，跳过。")
        return 1

    total = int(dur) // args.chunk + (1 if int(dur) % args.chunk else 0)
    log("视频时长 %02d:%02d:%02d，每段 %d 秒，共 %d 段"
        % (dur // 3600, dur % 3600 // 60, dur % 60, args.chunk, total))

    cache = {}
    if cache_path.exists() and not args.no_cache:
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if cache:
                log("发现上次的进度缓存，已完成 %d 段，继续。" % len(cache))
        except Exception:
            cache = {}

    all_items = []
    chunk_file = video.with_suffix(video.suffix + ".chunk.mp3")
    try:
        for i in range(total):
            start = i * args.chunk
            key = str(i)
            if key in cache:
                utterances = cache[key]
                log("[%d/%d] 使用缓存" % (i + 1, total))
            else:
                log("[%d/%d] 识别第 %s 起的音频……" % (i + 1, total, format_time(start * 1000)[:8]))
                extract_chunk(video, start, args.chunk, chunk_file)
                utterances = transcribe_chunk(chunk_file)
                cache[key] = utterances
                if not args.no_cache:
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            offset = start * 1000
            for u in utterances:
                text = (u.get("transcript") or "").strip()
                if not text:
                    continue
                all_items.append({
                    "transcript": text,
                    "start_time": int(u["start_time"]) + offset,
                    "end_time": int(u["end_time"]) + offset,
                })
    finally:
        if chunk_file.exists() and not args.keep_audio:
            try:
                chunk_file.unlink()
            except OSError:
                pass

    if not all_items:
        log("没有识别出任何文字。")
        return 1

    items = all_items if args.no_merge else merge_segments(all_items)
    srt_path.write_text(utterances_to_srt(items), encoding="utf-8")
    log("完成：%s（%d 条字幕）" % (srt_path.name, len(items)))

    if cache_path.exists() and not args.keep_audio:
        try:
            cache_path.unlink()
        except OSError:
            pass
    return 0


def main():
    parser = argparse.ArgumentParser(description="用 B 站必剪（Bcut）接口批量转字幕")
    parser.add_argument("paths", nargs="*", help="要处理的文件或文件夹，默认是脚本所在文件夹")
    parser.add_argument("--chunk", type=int, default=1200, help="每段音频秒数，默认 1200（20 分钟）")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的 .srt")
    parser.add_argument("--no-merge", action="store_true", help="不合并短句，输出原始逐句结果")
    parser.add_argument("--no-cache", action="store_true", help="不使用分片进度缓存")
    parser.add_argument("--keep-audio", action="store_true", help="保留中间文件（排查问题用）")
    args = parser.parse_args()

    print("=" * 42)
    print(" 批量转字幕工具（B 站必剪 Bcut 接口）")
    print("=" * 42)
    if not FFMPEG or not FFPROBE:
        print("找不到 ffmpeg / ffprobe，无法处理。")
        return 1
    print("ffmpeg : %s" % FFMPEG)

    videos = collect_videos(args.paths, Path(__file__).resolve().parent)
    if not videos:
        print("没有找到视频文件。")
        return 1
    print("待处理 : %d 个视频" % len(videos))

    ok = 0
    fail = 0
    for idx, video in enumerate(videos, 1):
        print()
        print("---------- [%d/%d] %s ----------" % (idx, len(videos), video.name))
        try:
            code = transcribe_video(video, args)
        except KeyboardInterrupt:
            print("用户中断。")
            return 130
        except Exception as exc:
            log("处理失败：%s" % exc)
            code = 1
        if code == 0:
            ok += 1
        else:
            fail += 1

    print()
    print("=" * 42)
    print(" 完成：成功 %d 个，失败 %d 个" % (ok, fail))
    print(" 字幕是外挂 .srt，和视频同目录、同文件名。")
    print("=" * 42)
    return 0


if __name__ == "__main__":
    sys.exit(main())
