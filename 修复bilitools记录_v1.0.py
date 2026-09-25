# -*- coding: utf-8 -*-
"""BiliTools 下载记录修复工具 v1.0

解决的问题：
    AppError: Cannot read properties of undefined (reading 'id')
        at /src/components/DownPage/Task.vue:3:15

原因：
    删掉下载任务之后，数据库 schedulers 表的 list 字段里还残留着
    已经不存在的任务编号，界面渲染到那一条时找不到任务对象，就报错。
    （这是软件自身的小 bug，作者已停止更新，只能从数据这边修。）

做法：
    把 schedulers.list 里指向"已不存在的任务"的编号去掉。
    改动前会自动把整个数据目录备份一份。

用法：
    1. 完全退出 BiliTools（托盘图标也要退）
    2. 双击同目录的「修复记录.bat」，或运行 python 修复bilitools记录_v1.0.py
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

VERSION = "1.0"

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def say(text=""):
    print(text, flush=True)


def data_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "com.btjawa.bilitools")


def running(name):
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/NH"],
                             capture_output=True, text=True).stdout
        return name.lower() in (out or "").lower()
    except Exception:
        return False


def main():
    say("=" * 48)
    say(" BiliTools 下载记录修复工具  v%s" % VERSION)
    say("=" * 48)

    d = data_dir()
    if not d or not os.path.isdir(d):
        say("找不到 BiliTools 的数据目录：%s" % d)
        return 1
    db = os.path.join(d, "Storage")
    if not os.path.isfile(db):
        say("找不到数据库文件：%s" % db)
        return 1
    say("数据目录：%s" % d)

    # 1. 必须先把软件关掉
    busy = [n for n in ("bilitools.exe", "aria2c.exe") if running(n)]
    if busy:
        say("")
        say("！！ BiliTools 还在运行（%s），请先完全退出再运行本工具。" % "、".join(busy))
        say("   （包括右下角托盘图标：右键 → 退出）")
        return 1

    # 2. 备份
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(d, "backup_%s" % stamp)
    os.makedirs(bak, exist_ok=True)
    copied = []
    for n in ("Storage", "Storage-shm", "Storage-wal"):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(bak, n))
            copied.append(n)
    say("")
    say("已备份到：%s" % bak)
    say("  备份文件：%s" % "、".join(copied))

    # 3. 修复
    con = sqlite3.connect(db)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM tasks")
        have = {r[0] for r in cur.fetchall()}

        cur.execute("SELECT name, list FROM schedulers")
        rows = cur.fetchall()
        fixed = []
        for name, lst in rows:
            try:
                ids = json.loads(lst) if lst else []
            except Exception:
                ids = []
            if not isinstance(ids, list):
                continue
            keep = [i for i in ids if i in have]
            if len(keep) != len(ids):
                removed = [i for i in ids if i not in have]
                cur.execute("UPDATE schedulers SET list = ? WHERE name = ?",
                            (json.dumps(keep), name))
                fixed.append((name, removed, len(keep)))

        # 顺手清理：tasks 表里 meta/prepare 为空的坏记录
        cur.execute("SELECT name, meta, prepare FROM tasks")
        bad = [n for n, m, p in cur.fetchall()
               if not m or m in ("null", "{}") or not p or p in ("null", "{}")]
        for n in bad:
            cur.execute("DELETE FROM tasks WHERE name = ?", (n,))

        con.commit()
    finally:
        con.close()

    say("")
    if not fixed and not bad:
        say("检查完毕：没有发现坏掉的记录，不需要修复。")
        return 0
    for name, removed, left in fixed:
        say("修复调度记录 %s：去掉 %d 个无效任务编号 %s，剩余 %d 个"
            % (name, len(removed), removed, left))
    if bad:
        say("删除空的坏任务记录：%s" % "、".join(bad))
    say("")
    say("修复完成。现在可以重新打开 BiliTools 了。")
    say("如果还报同样的错，把本窗口的内容发我。")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        say("出错：%s" % e)
        code = 1
    if sys.stdout.isatty():
        try:
            input("按回车退出……")
        except EOFError:
            pass
    sys.exit(code)
