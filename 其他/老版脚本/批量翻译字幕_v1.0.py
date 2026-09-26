# -*- coding: utf-8 -*-
# 批量翻译字幕（免费接口，不需要 API Key）
#
# 内置三个免费引擎（都不需要 API Key）：
#   transmart  腾讯交互翻译，国内直连不用 VPN，支持一次传多行   ← 默认
#   youdao     有道翻译 demo 接口，国内直连不用 VPN
#   google     Google 免费网页接口，免 Key 但国内要走代理
#
# 用法示例：
#   python 批量翻译字幕.py                        处理脚本所在文件夹里所有 .srt
#   python 批量翻译字幕.py "D:\某个文件夹"          处理指定文件夹
#   python 批量翻译字幕.py a.srt b.srt             处理指定文件
#   python 批量翻译字幕.py --engine google         换引擎（默认 transmart）
#   python 批量翻译字幕.py --to en                 目标语言（默认 zh-CN）
#   python 批量翻译字幕.py --threads 6 --batch 8   并发线程数 / 每次请求合并几行
#   python 批量翻译字幕.py --proxy http://127.0.0.1:7897
#   python 批量翻译字幕.py --no-bilingual          只输出译文，不输出双语
#   python 批量翻译字幕.py --overwrite             覆盖已存在的输出
#
# 输出：
#   xxx.zh.srt        纯译文
#   xxx.bilingual.srt 中英对照（原文在上，译文在下）
#   xxx.transcache.json  翻译缓存，中断后重跑不会重复翻译

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GTX = "https://translate.googleapis.com/translate_a/single?client=gtx&dt=t"
CHROME_EXT = "https://clients5.google.com/translate_a/t?client=dict-chrome-ex"
ENDPOINTS = [GTX, CHROME_EXT]

TRANSMART = "https://transmart.qq.com/api/imt"
YOUDAO = "https://aidemo.youdao.com/trans"

# 各引擎的目标语言写法
TRANSMART_LANGS = {"zh-cn": "zh", "zh": "zh", "en": "en", "ja": "ja", "ko": "ko",
                   "fr": "fr", "de": "de", "ru": "ru", "es": "es"}

MAX_Q_CHARS = 2500          # 单次请求最大字符数，留足余量（Google 上限约 5000）
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_opener = None
_opener_lock = threading.Lock()
_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def build_opener(proxy: str | None):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    handlers.append(urllib.request.HTTPCookieProcessor())
    return urllib.request.build_opener(*handlers)


def get_opener(proxy: str | None):
    global _opener
    if _opener is None:
        with _opener_lock:
            if _opener is None:
                _opener = build_opener(proxy)
    return _opener


def parse_response(raw: str) -> str:
    """兼容 gtx 和 dict-chrome-ex 两种返回格式"""
    data = json.loads(raw)
    if isinstance(data, dict):
        if "sentences" in data:
            return "".join(seg.get("trans", "") for seg in data["sentences"])
        return data.get("trans", "") or ""
    if data and isinstance(data[0], list):
        # [[["译文","原文",...], ...], ...]
        return "".join(seg[0] for seg in data[0] if seg and seg[0])
    if data and isinstance(data[0], str):
        return "".join(data)
    return ""


def translate_text(text: str, src: str, dst: str, proxy: str | None) -> str:
    """翻译一段文本（可含换行），失败抛异常"""
    opener = get_opener(proxy)
    last_err = None
    for attempt, ep in enumerate(ENDPOINTS):
        if ep is GTX:
            url = "%s&sl=%s&tl=%s&q=%s" % (ep, src, dst, urllib.parse.quote(text))
        else:
            url = "%s&sl=%s&tl=%s&q=%s" % (ep, src, dst, urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with opener.open(req, timeout=30) as resp:
                return parse_response(resp.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError("all endpoints failed: %s" % last_err)


def translate_with_retry(text, src, dst, proxy, tries=5):
    delay = 1.0
    for i in range(tries):
        try:
            return translate_text(text, src, dst, proxy)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            log("重试 %d/%d：%s" % (i + 1, tries, e))
            time.sleep(delay)
            delay = min(delay * 2, 20)
    return ""


def _tgt(engine, to: str) -> str:
    if engine in ("transmart", "youdao"):
        low = to.lower()
        if engine == "transmart":
            return TRANSMART_LANGS.get(low, "zh")
        # 有道的写法是 zh-CHS / zh-CHT / en / ja ...
        if low.startswith("zh-hant") or low in ("zh-tw", "zh-hk"):
            return "zh-CHT"
        if low.startswith("zh"):
            return "zh-CHS"
        return to.split("-")[0]
    return to


def transmart_translate(texts, src, to, proxy):
    """腾讯交互翻译，一次可以传多行，返回顺序与传入一致"""
    if not texts:
        return []
    opener = get_opener(proxy)
    payload = {
        "header": {
            "fn": "auto_translation",
            "client_key": "browser-chrome-131.0.0.0-20260101",
            "session": "",
            "user": "",
        },
        "type": "plain",
        "model_category": "normal",
        "source": {"lang": src or "auto", "text_list": texts},
        "target": {"lang": _tgt("transmart", to)},
    }
    req = urllib.request.Request(
        TRANSMART,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Referer": "https://transmart.qq.com/zh-CN/index"},
    )
    with opener.open(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    out = data.get("auto_translation")
    if data.get("header", {}).get("ret_code") != "succ" or not isinstance(out, list):
        raise RuntimeError("transmart error: %s" % json.dumps(data, ensure_ascii=False)[:200])
    if len(out) != len(texts):
        raise RuntimeError("transmart 行数不匹配 %d -> %d" % (len(texts), len(out)))
    return out


def youdao_translate(text, src, to, proxy):
    """有道 demo 接口，一次一行"""
    opener = get_opener(proxy)
    data = urllib.parse.urlencode({
        "q": text,
        "from": src or "auto",
        "to": _tgt("youdao", to),
    }).encode("utf-8")
    req = urllib.request.Request(
        YOUDAO, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA},
    )
    with opener.open(req, timeout=40) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    if data.get("errorCode") not in ("0", 0):
        raise RuntimeError("youdao error: %s" % data.get("errorCode"))
    tr = data.get("translation") or [""]
    return tr[0] if isinstance(tr, list) else str(tr)


def transmart_with_retry(texts, src, to, proxy, tries=5):
    delay = 1.0
    for i in range(tries):
        try:
            return transmart_translate(texts, src, to, proxy)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            log("transmart 重试 %d/%d：%s" % (i + 1, tries, e))
            time.sleep(delay)
            delay = min(delay * 2, 20)
    return []


def parse_srt(content: str):
    """把 srt 拆成 [{index, timecode, text}, ...]"""
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []
    for blk in blocks:
        lines = blk.split("\n")
        if len(lines) < 2:
            continue
        # 有的文件没有序号行，兼容一下
        if "-->" in lines[0]:
            idx, tc, body_start = str(len(entries) + 1), lines[0].strip(), 1
        else:
            idx, tc, body_start = lines[0].strip(), lines[1].strip(), 2
        if "-->" not in tc:
            continue
        body = "\n".join(lines[body_start:]).strip()
        entries.append({"index": idx, "timecode": tc, "text": body})
    return entries


def build_batches(entries, batch_size, max_chars=MAX_Q_CHARS):
    """按行数和字符数双重限制切批，返回 [(起始下标, [条目...]), ...]"""
    batches, cur, cur_chars, start = [], [], 0, 0
    for i, e in enumerate(entries):
        if not cur:
            start = i
        one_line = re.sub(r"\s*\n\s*", " ", e["text"]).strip()
        cur.append((i, one_line))
        cur_chars += len(one_line) + 1
        if len(cur) >= batch_size or cur_chars >= max_chars:
            batches.append((start, cur))
            cur, cur_chars = [], 0
    if cur:
        batches.append((start, cur))
    return batches


def google_batch(texts, src, dst, proxy):
    """Google 用换行拼一批，行数对不上就逐行重翻"""
    if len(texts) == 1:
        return [translate_with_retry(texts[0], src, dst, proxy)]
    joined = "\n".join(texts)
    try:
        out = translate_with_retry(joined, src, dst, proxy)
        parts = [p.strip() for p in out.split("\n")]
        if len(parts) == len(texts):
            return parts
        raise ValueError("行数不匹配 %d -> %d" % (len(texts), len(parts)))
    except Exception as e:  # noqa: BLE001
        log("Google 合并翻译对不上（%s），改为逐行翻译 %d 行" % (e, len(texts)))
        return [translate_with_retry(t, src, dst, proxy) for t in texts]


def translate_batch(batch, args, cache, cache_lock):
    """返回 {下标: 译文}"""
    src, dst, proxy, engine = args.src, args.to, args.proxy, args.engine
    prefix = "%s|%s|" % (engine, dst)
    result, todo = {}, []

    for i, t in batch:
        with cache_lock:
            hit = cache.get(prefix + t)
        if hit:
            result[i] = hit
        else:
            todo.append((i, t))
    if not todo:
        return result

    texts = [t for _, t in todo]
    if engine == "transmart":
        outs = transmart_with_retry(texts, src, dst, proxy)
    elif engine == "youdao":
        outs = []
        for t in texts:
            try:
                outs.append(youdao_translate(t, src, dst, proxy))
            except Exception as e:  # noqa: BLE001
                log("有道失败，回退 Google：%s" % e)
                outs.append(translate_with_retry(t, "auto", "zh-CN", proxy))
    else:
        outs = google_batch(texts, src, dst, proxy)

    for (i, _), o in zip(todo, outs):
        result[i] = (o or "").strip()
    with cache_lock:
        for (i, t), o in zip(todo, outs):
            cache[prefix + t] = result.get(i, "")
    return result


def process_srt(path: Path, args, cache, cache_lock, cache_path: Path):
    content = path.read_text(encoding="utf-8", errors="replace")
    entries = parse_srt(content)
    if not entries:
        log("跳过（没解析出字幕条目）：%s" % path.name)
        return

    lang = args.to.split("-")[0]
    out_zh = path.with_suffix(".%s.srt" % lang)
    out_bi = path.with_suffix(".%s.bilingual.srt" % lang)
    if out_zh.exists() and not args.overwrite:
        log("已存在，跳过（--overwrite 可强制覆盖）：%s" % out_zh.name)
        return

    max_chars = 6000 if args.engine == "transmart" else MAX_Q_CHARS
    batches = build_batches(entries, args.batch, max_chars)
    log("%s：%d 条字幕，切成 %d 批，%d 线程" % (path.name, len(entries), len(batches), args.threads))

    done = [0]
    total = [len(entries)]

    def work(b):
        start, batch = b
        return start, translate_batch(batch, args, cache, cache_lock)

    results = {}
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        for _, part in pool.map(work, batches):
            results.update(part)
            done[0] = len(results)
            if done[0] % 200 < args.batch or done[0] == total[0]:
                log("进度 %d/%d" % (done[0], total[0]))
                with cache_lock:
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # 写文件
    zh_chunks, bi_chunks = [], []
    for i, e in enumerate(entries):
        zh = results.get(i, "").strip()
        zh_chunks.append("%s\n%s\n%s\n" % (e["index"], e["timecode"], zh))
        bi_chunks.append("%s\n%s\n%s\n%s\n" % (e["index"], e["timecode"],
                                               e["text"], zh))
    out_zh.write_text("\n".join(zh_chunks), encoding="utf-8")
    if not args.no_bilingual:
        out_bi.write_text("\n".join(bi_chunks), encoding="utf-8")
    with cache_lock:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log("完成：%s" % out_zh.name + ("" if args.no_bilingual else " 和 %s" % out_bi.name))


def collect_targets(args):
    exts = {".srt"}
    targets = []
    if args.inputs:
        for item in args.inputs:
            p = Path(item)
            if p.is_dir():
                targets += sorted(f for f in p.iterdir() if f.suffix.lower() in exts)
            elif p.is_file():
                targets.append(p)
            else:
                log("找不到：%s" % item)
    else:
        here = Path(__file__).resolve().parent
        targets = sorted(f for f in here.iterdir() if f.suffix.lower() in exts)
    # 别把自己生成的译文再翻一遍
    targets = [t for t in targets
               if not re.search(r"\.(zh|en|ja|ko|bilingual)\.srt$", t.name, re.I)]
    return targets


def main():
    ap = argparse.ArgumentParser(description="批量翻译字幕（免费接口，无需 Key）")
    ap.add_argument("inputs", nargs="*", help="文件或文件夹，留空则处理脚本所在文件夹")
    ap.add_argument("--engine", default="transmart", choices=["transmart", "youdao", "google"],
                    help="翻译引擎：transmart=腾讯（默认，免 VPN）/ youdao=有道（免 VPN）/ google（要代理）")
    ap.add_argument("--from", dest="src", default="auto", help="源语言，默认 auto 自动识别")
    ap.add_argument("--to", dest="to", default="zh-CN", help="目标语言，默认 zh-CN")
    ap.add_argument("--threads", type=int, default=6, help="并发线程数，默认 6")
    ap.add_argument("--batch", type=int, default=0, help="每次请求合并几行，0 表示按引擎自动")
    ap.add_argument("--proxy", default=None, help="形如 http://127.0.0.1:7897，留空用系统代理")
    ap.add_argument("--no-bilingual", action="store_true", help="不输出双语文件")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出")
    args = ap.parse_args()

    if args.batch <= 0:
        args.batch = {"transmart": 20, "google": 6, "youdao": 1}[args.engine]

    targets = collect_targets(args)
    if not targets:
        log("没有找到 .srt 文件")
        return

    # 缓存放在 %LOCALAPPDATA%\SubtitleTranslate，避免弄脏脚本所在文件夹（尤其是 git 仓库）
    cache_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SubtitleTranslate"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache_dir = Path(__file__).resolve().parent
    cache_path = cache_dir / ".translate_cache.json"
    cache, cache_lock = {}, threading.Lock()
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}

    for t in targets:
        process_srt(t, args, cache, cache_lock, cache_path)


if __name__ == "__main__":
    main()
