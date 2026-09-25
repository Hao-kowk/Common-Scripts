# -*- coding: utf-8 -*-
"""BiliTools 下载文件改名工具 v1.0

把 BiliTools 默认模板生成的长文件名：
    1-环世界26_9_1--2026-09-22_21-19-14-合成弹幕版P1-视频-视频-2026-09-17_23-55-58.mp4
改成短名字：
    1-环世界2691-合成弹幕版P1.mp4

规则：{序号}-{合集名去掉下划线斜杠和结尾横线}-{分P名}.mp4
用法：把本文件放到下载目录里（或把目录拖到本文件上），双击运行。
"""

import os
import re
import sys

VERSION = "1.0"

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DT = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
MEDIA_WORDS = {"视频", "音频", "弹幕", "图片", "封面", "字幕", "合并"}
LOG_NAME = "改名记录.txt"


def say(text=""):
    print(text, flush=True)


def clean(text):
    """合集名清理：去掉 / \\ : _ 空格，再去掉首尾的横线。"""
    for ch in "/\\:：_":
        text = text.replace(ch, "")
    text = text.replace(" ", "")
    return text.strip("-_")


def parse(stem):
    """拆解 BiliTools 生成的文件名，返回各部分。"""
    m = re.match(r"^(\d+)[-_](.+)$", stem)
    if not m:
        return None
    index, rest = m.group(1), m.group(2)

    dts = [x.group(0) for x in DT.finditer(rest)]
    if not dts:
        # 没有时间戳的短模板（{index}-{showtitle}-{title}）也支持
        if "--" in rest:
            show, title = rest.split("--", 1)
        else:
            show, title = rest, ""
        return {"index": index, "show": show.strip("-_ "),
                "title": title.strip("-_ "), "downtime": None, "pubtime": None}
    downtime = dts[0]
    i = rest.find(downtime)
    show = rest[:i].strip("-_ ")
    after = rest[i + len(downtime):].strip("-_ ")

    pubtime = None
    dts2 = [x.group(0) for x in DT.finditer(after)]
    if dts2:
        pubtime = dts2[-1]
        j = after.rfind(pubtime)
        after = after[:j].strip("-_ ")

    while True:
        parts = after.rsplit("-", 1)
        if len(parts) == 2 and parts[1].strip() in MEDIA_WORDS:
            after = parts[0].strip("-_ ")
        else:
            break

    return {"index": index, "show": show, "title": after, "downtime": downtime, "pubtime": pubtime}


def target_name(stem, ext):
    info = parse(stem)
    if not info:
        return None
    bits = [info["index"]]
    show = clean(info["show"])
    if show:
        bits.append(show)
    title = clean(info["title"])
    if title:
        bits.append(title)
    return "-".join(bits) + ext


def collect(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith("_")]
        for fn in sorted(filenames):
            if fn.lower().endswith((".mp4", ".mkv", ".flv", ".m4a", ".mp3")):
                found.append(os.path.join(dirpath, fn))
    return found


def main():
    say("=" * 44)
    say(" BiliTools 下载文件改名工具  v%s" % VERSION)
    say("=" * 44)

    root = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        root = os.path.abspath(sys.argv[1])
    say("目录：%s" % root)

    files = collect(root)
    plan, skipped = [], []
    used = {}
    for path in files:
        d = os.path.dirname(path)
        stem, ext = os.path.splitext(os.path.basename(path))
        new = target_name(stem, ext)
        if not new or new == os.path.basename(path):
            skipped.append(path)
            continue
        target = os.path.join(d, new)
        if os.path.exists(target) or used.get(target):
            base, e = os.path.splitext(new)
            n = 2
            while os.path.exists(os.path.join(d, "%s (%d)%s" % (base, n, e))) or used.get(os.path.join(d, "%s (%d)%s" % (base, n, e))):
                n += 1
            new = "%s (%d)%s" % (base, n, e)
            target = os.path.join(d, new)
        used[target] = True
        plan.append((path, target, new))

    say("")
    say("找到可改名的文件 %d 个，跳过 %d 个（名字不符合模板或已经是短名）" % (len(plan), len(skipped)))
    if not plan:
        say("没有需要改的。")
        return 0

    say("")
    say("改名预览：")
    for src, dst, new in plan:
        say("  %s" % os.path.basename(src))
        say("      -> %s" % new)

    say("")
    try:
        ans = input("按回车执行改名，输入 0 取消：").strip().lstrip("\ufeff")
    except EOFError:
        ans = ""
    if ans.startswith("0"):
        say("已取消，没有改动任何文件。")
        return 0

    ok = 0
    fail = 0
    log_path = os.path.join(root, LOG_NAME)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("\n=== %s  v%s ===\n" % (__import__("time").strftime("%Y-%m-%d %H:%M:%S"), VERSION))
        for src, dst, new in plan:
            try:
                os.rename(src, dst)
                ok += 1
                log.write("%s  ->  %s\n" % (os.path.basename(src), new))
            except OSError as e:
                fail += 1
                say("  失败：%s（%s）" % (os.path.basename(src), e))
                log.write("失败 %s（%s）\n" % (os.path.basename(src), e))

    say("")
    say("完成：改名 %d 个，失败 %d 个。记录写在 %s" % (ok, fail, LOG_NAME))
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
