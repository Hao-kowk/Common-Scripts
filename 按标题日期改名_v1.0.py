# -*- coding: utf-8 -*-
"""按视频标题里的日期改名 v1.0

背景：
    BiliTools 的命名模板里拿不到"视频标题"，只拿得到合集名，
    而录制日期是写在视频标题里的（例如 【太原杨树】2026/9/14 环世界 弹幕版&纯享版录播）。
    能区分每一期的唯一信息是 BV 号。

做法：
    1. BiliTools 的文件名模板里带上 BV 号，例如：
           {bvid}_{title}
       → BV15We56XEqe_合成弹幕版P1.mp4
    2. 本工具扫描文件名里的 BV 号，去 B 站公开接口取真实标题，
       把标题里的日期提到名字最前面：
           BV15We56XEqe_合成弹幕版P1.mp4  →  09-14_合成弹幕版P1.mp4

用法：
    双击本文件（处理所在目录），或把文件夹拖到本文件上。
    先显示预览，按回车才真正改名。
"""

import json
import os
import re
import sys
import time
import urllib.request

VERSION = "1.0"

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
DATE_RE = re.compile(r"(20\d{2})\s*[/\-\.年]\s*(\d{1,2})\s*[/\-\.月]\s*(\d{1,2})")
VIDEO_EXT = {".mp4", ".mkv", ".flv", ".m4v", ".webm", ".ts", ".mov"}
CACHE_NAME = ".bvid_title_cache.json"


def say(text=""):
    print(text, flush=True)


def load_cache(root):
    p = os.path.join(root, CACHE_NAME)
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(root, cache):
    try:
        with open(os.path.join(root, CACHE_NAME), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def fetch_title(bv, cache):
    if bv in cache:
        return cache[bv]
    url = "https://api.bilibili.com/x/web-interface/view?bvid=" + bv
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        title = (data.get("data") or {}).get("title") or ""
    except Exception as e:
        title = ""
        say("    （查询失败：%s）" % e)
    cache[bv] = title
    time.sleep(0.5)
    return title


def clean(text):
    for ch in "/\\:：_":
        text = text.replace(ch, "")
    return text.replace(" ", "").strip("-_")


def target_name(name, title, full=False):
    """根据标题里的日期生成新文件名；找不到日期就返回 None。"""
    stem, ext = os.path.splitext(name)
    if ext.lower() not in VIDEO_EXT:
        return None
    m = DATE_RE.search(title or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    date = "%04d-%02d-%02d" % (y, mo, d) if full else "%02d-%02d" % (mo, d)
    rest = BV_RE.sub("", stem)          # 去掉 BV 号
    if "--" in rest:                    # 兼容 {showtitle}{title}-{bvid} 这种命名：
        rest = rest.rsplit("--", 1)[-1] # 去掉前面的合集名，只留下分P名
    rest = clean(rest)                  # 去掉多余的下划线等
    rest = rest.strip("-")
    if not rest:
        rest = "视频"
    return "%s_%s%s" % (date, rest, ext)


def collect(root, recursive=True):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        if not recursive and os.path.normpath(dirpath) != os.path.normpath(root):
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith("_")]
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() in VIDEO_EXT and BV_RE.search(fn):
                found.append(os.path.join(dirpath, fn))
    return found


def main():
    say("=" * 50)
    say(" 按视频标题里的日期改名  v%s" % VERSION)
    say("=" * 50)

    root = os.path.dirname(os.path.abspath(__file__))
    full = False
    for a in sys.argv[1:]:
        if a in ("--full", "-f"):
            full = True
        elif os.path.isdir(a):
            root = os.path.abspath(a)
        elif os.path.isfile(a):
            root = os.path.dirname(os.path.abspath(a))
    say("目录：%s" % root)
    say("日期格式：%s" % ("YYYY-MM-DD" if full else "MM-DD"))

    files = collect(root)
    if not files:
        say("")
        say("没有找到带 BV 号的文件名。")
        say("请先把 BiliTools 的文件名模板改成带 BV 号的，例如：  {bvid}_{title}")
        return 0

    cache = load_cache(root)
    plan = []
    say("")
    say("正在查询 %d 个文件的标题……" % len(files))
    for path in files:
        name = os.path.basename(path)
        bv = BV_RE.search(name).group(0)
        title = fetch_title(bv, cache)
        new = target_name(name, title, full)
        if not new or new == name:
            plan.append((path, None, title, "无法处理"))
            continue
        newpath = os.path.join(os.path.dirname(path), new)
        n = 2
        base, ext = os.path.splitext(new)
        while os.path.exists(newpath) and newpath != path:
            newpath = os.path.join(os.path.dirname(path), "%s (%d)%s" % (base, n, ext))
            n += 1
        plan.append((path, newpath, title, "ok"))
    save_cache(root, cache)

    todo = [p for p in plan if p[1]]
    say("")
    say("改名预览（%d 个）：" % len(todo))
    for src, dst, title, st in plan:
        if dst:
            say("  %s" % os.path.basename(src))
            say("    标题：%s" % title)
            say("    → %s" % os.path.basename(dst))
        else:
            say("  [跳过] %s（%s）" % (os.path.basename(src), title or "取不到标题"))

    if not todo:
        say("")
        say("没有可改名的文件。")
        return 0

    say("")
    try:
        ans = input("按回车执行改名，输入 0 取消：").strip().lstrip("\ufeff")
    except EOFError:
        ans = ""
    if ans.startswith("0"):
        say("已取消，没有改动任何文件。")
        return 0

    ok = fail = 0
    log = os.path.join(root, "改名记录.txt")
    with open(log, "a", encoding="utf-8") as f:
        f.write("\n=== %s  v%s ===\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), VERSION))
        for src, dst, title, st in todo:
            try:
                os.rename(src, dst)
                ok += 1
                f.write("%s  →  %s\n" % (os.path.basename(src), os.path.basename(dst)))
            except OSError as e:
                fail += 1
                say("  失败：%s（%s）" % (os.path.basename(src), e))
    say("")
    say("完成：改名 %d 个，失败 %d 个。记录写在 %s" % (ok, fail, "改名记录.txt"))
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
