# -*- coding: utf-8 -*-
"""FY-4B 卫星云图抓取 — 中央气象台免费实时云图, 15 分钟一张 (文件名时间 = UTC).
日落时刻图 = 验证"西边到底有没有云"的客观依据."""
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://image.nmc.cn/product/{y}/{m}/{d}/WXBL/medium/SEVP_NSMC_WXBL_FY4B_ETCC_ACHN_LNO_PY_{t}00000.JPG"
SAT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sat")


def sunset_utc_slot(local_date, sunset_hhmm):
    """本地(北京)日落时刻 -> 对应 UTC 时刻, 向下取到 15 分钟."""
    t = datetime.strptime(f"{local_date} {sunset_hhmm}", "%Y-%m-%d %H:%M")
    utc = t - timedelta(hours=8)
    utc = utc.replace(minute=utc.minute - utc.minute % 15, second=0)
    return utc


def fetch_sat(local_date, sunset_hhmm):
    """抓日落时刻卫星云图, 存到按 UTC 档位去重的路径 (同一时刻全国一张图, 所有城市共用).
    已存在则直接复用. 返回 (图像时间戳, 保存路径)."""
    utc = sunset_utc_slot(local_date, sunset_hhmm)
    out_path = os.path.join(SAT_DIR, f"{utc.strftime('%Y%m%d_%H%M')}utc.jpg")
    if os.path.exists(out_path):
        return utc.strftime("%Y-%m-%d %H:%M UTC"), out_path
    url = BASE.format(y=utc.strftime("%Y"), m=utc.strftime("%m"), d=utc.strftime("%d"),
                      t=utc.strftime("%Y%m%d%H%M"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            os.makedirs(SAT_DIR, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)
            return utc.strftime("%Y-%m-%d %H:%M UTC"), out_path
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def satellite_static(rel):
    """从保存路径取静态文件相对 URL."""
    return "/img/" + rel.replace("\\", "/")
