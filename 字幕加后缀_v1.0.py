# -*- coding: utf-8 -*-
"""字幕加后缀 v1.0

做的事（很简单）：
    1. 把文件夹里所有 .srt 的字名字加上「_音量压缩」
         原名：杨树9_21世界 -弹幕版P1.srt
         改名：杨树9_21世界 -弹幕版P1_音量压缩.srt
    2. 如果同目录下有「_处理后」文件夹，而且里面正好有对应的成品视频
         杨树9_21世界 -弹幕版P1_音量压缩.mp4
       就把改好名的字幕再复制一份进去，让播放器打开成品时能自动加载字幕。
       （源视频旁边那份字幕会保留，不会被删）

用法：
    双击本文件（处理它所在的文件夹），或把文件夹拖到本文件上。
    先显示预览，按回车才动手；输入 0 取消。
    名字里已经带「_音量压缩」的字幕会自动跳过。
"""

import os
import shutil
import sys
import time

VERSION = "1.0"
SUFFIX = "_音量压缩"
VIDEO_EXTS = (".mp4", ".mkv", ".flv", ".m4v", ".ts", ".webm", ".avi")

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def say(text=""):
    print(text, flush=True)


def main():
    say("=" * 44)
    say(" 字幕加后缀  v%s" % VERSION)
    say("=" * 44)

    root = os.path.dirname(os.path.abspath(__file__))
    for a in sys.argv[1:]:
        if os.path.isdir(a):
            root = os.path.abspath(a)
        elif os.path.isfile(a):
            root = os.path.dirname(os.path.abspath(a))
    say("目录：%s" % root)
    say("规则：字幕名字加「%s」；成品在旁边「_处理后」里的话，再复制一份到那儿" % SUFFIX)

    srts = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.lower().endswith(".srt"):
                srts.append(os.path.join(dirpath, fn))

    if not srts:
        say("")
        say("这个目录里没有 .srt 字幕文件。")
        return 0

    renames, copies, skipped, conflicts = [], [], [], []
    for srt in srts:
        d = os.path.dirname(srt)
        base, ext = os.path.splitext(os.path.basename(srt))
        if base.endswith(SUFFIX):
            skipped.append(srt)
            continue
        newname = base + SUFFIX + ext
        target = os.path.join(d, newname)
        if os.path.exists(target):
            conflicts.append((srt, target))
            continue
        renames.append((srt, target))

        # 成品在 _处理后 里的话，也复制一份过去
        proc_dir = os.path.join(d, "_处理后")
        if os.path.isdir(proc_dir):
            for vext in VIDEO_EXTS:
                if os.path.isfile(os.path.join(proc_dir, base + SUFFIX + vext)):
                    copies.append((target, os.path.join(proc_dir, newname)))
                    break

    say("")
    say("找到字幕 %d 个：已带后缀跳过 %d 个，改名 %d 个，其中 %d 个要复制进 _处理后"
        % (len(srts), len(skipped), len(renames), len(copies)))
    for src, dst in renames:
        say("  改名  %s" % os.path.relpath(src, root))
        say("     →  %s" % os.path.relpath(dst, root))
    for src, dst in copies:
        say("  复制  %s" % os.path.relpath(src, root))
        say("     →  %s" % os.path.relpath(dst, root))
    for src, dst in conflicts:
        say("  [跳过] %s（目标已存在）" % os.path.relpath(src, root))

    if not renames:
        say("")
        say("没有需要处理的。")
        return 0

    say("")
    try:
        ans = input("按回车开始，输入 0 取消：").strip().lstrip("\ufeff")
    except EOFError:
        ans = ""
    if ans.startswith("0"):
        say("已取消，没有改动任何文件。")
        return 0

    ok = fail = 0
    log = os.path.join(root, "字幕加后缀记录.txt")
    with open(log, "a", encoding="utf-8") as f:
        f.write("\n=== %s  v%s ===\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), VERSION))
        for src, dst in renames:
            try:
                os.rename(src, dst)
                ok += 1
                f.write("改名  %s  →  %s\n" % (os.path.relpath(src, root), os.path.relpath(dst, root)))
            except OSError as e:
                fail += 1
                say("  改名失败：%s（%s）" % (os.path.basename(src), e))
        for src, dst in copies:
            try:
                shutil.copy2(src, dst)
                f.write("复制  %s  →  %s\n" % (os.path.relpath(src, root), os.path.relpath(dst, root)))
            except OSError as e:
                say("  复制失败：%s（%s）" % (os.path.basename(src), e))

    say("")
    say("完成：改名 %d 个，复制 %d 个，失败 %d 个。" % (ok, len(copies), fail))
    say("记录写在 字幕加后缀记录.txt")
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
