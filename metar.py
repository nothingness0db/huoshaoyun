# -*- coding: utf-8 -*-
"""机场 METAR 观测报 — 历史实况数据源 (aviationweather.gov 免费, 无 key).
METAR 每小时一份, 报云层(高度/量)/能见度/天气现象/温湿, 是真正的气象站观测.
"""
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

METAR_URL = "https://aviationweather.gov/api/data/metar"
UA = {"User-Agent": "Mozilla/5.0"}

# 城市 -> 机场 ICAO 候选列表 (第一个有数据的用)
ICAO = {
    "香洲": ["ZGSD", "ZGSZ"], "金湾": ["ZGSD", "ZGSZ"], "斗门": ["ZGSD", "ZGSZ"],
    "广州": ["ZGGG", "ZGSZ"], "深圳": ["ZGSZ"], "佛山": ["ZGFS", "ZGGG"],
    "东莞": ["ZGSZ"], "中山": ["ZGSD", "ZGSZ"], "惠州": ["ZGHZ", "ZGSZ"],
    "江门": ["ZGSD", "ZGSZ"], "肇庆": ["ZGGG"],
    "香港": ["VHHH"], "澳门": ["VMMC", "ZGSD", "ZGSZ"],
    "厦门": ["ZSAM"], "上海": ["ZSSS", "ZSPD"],
    "南宁": ["ZGNN"], "桂林": ["ZGKL"], "柳州": ["ZGZH"], "北海": ["ZGBH"],
    "梧州": ["ZGWZ"], "玉林": ["ZGYL", "ZGWZ"],
    "北京": ["ZBAA", "ZBTJ"], "成都": ["ZUUU", "ZUTF"],
    "昆明": ["ZPPP"], "拉萨": ["ZULS"],
    "哈尔滨": ["ZYHB"], "海口": ["ZJHK"],
}

COVER_AMT = {"FEW": 1 / 8, "SCT": 3 / 8, "BKN": 5 / 8, "OVC": 8 / 8, "VV": 8 / 8}


def fetch_metars(icao, start, end):
    """拉取 [start, end] 区间 (UTC, datetime) 的全部 METAR JSON.
    hours 参数是相对当前时刻的窗口, 需覆盖从 start 到现在 (API 上限 720h ≈ 30 天)."""
    span = (datetime.utcnow() - start).total_seconds() / 3600
    hours = int(min(720, max(24, span + 6)))
    qs = f"ids={icao}&format=json&hours={hours}"
    req = urllib.request.Request(f"{METAR_URL}?{qs}", headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if not data.strip():
                return []                     # 该机场不在此数据源
            rows = json.loads(data.decode("utf-8", "ignore"))
            t0, t1 = int(start.timestamp()), int(end.timestamp())
            return [m for m in rows if t0 <= m.get("obsTime", 0) < t1]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def rh_from_td(t, td):
    """Magnus 公式: 温度/露点(C) -> 相对湿度(%)"""
    if t is None or td is None:
        return None
    e = math.exp((17.625 * td) / (243.04 + td)) / math.exp((17.625 * t) / (243.04 + t))
    return max(0.0, min(100.0, 100 * e))


def metar_factors(report):
    """METAR 报文 -> (高云%, 中云%, 低云%, 湿度%, 降水概率, AOD=None).
    云高分层: 低 <2000m, 中 2000~6000m, 高 >6000m (与 Open-Meteo 分层口径近似)."""
    low = mid = high = 0.0
    for c in report.get("clouds") or []:
        amt = COVER_AMT.get(c.get("cover", ""), 0) * 100
        base_m = (c.get("base") or 0) / 3.2808
        if base_m < 2000:
            low = max(low, amt)
        elif base_m <= 6000:
            mid = max(mid, amt)
        else:
            high = max(high, amt)
    rh = rh_from_td(report.get("temp"), report.get("dewp"))
    raw = report.get("rawOb", "")
    precip = 100.0 if any(w in raw for w in ("RA", "DZ", "TS", "SHRA", "SN", "+RA")) else 0.0
    return round(high), round(mid), round(low), round(rh) if rh else None, precip, None


def nearest_metar(metars, target_ts):
    """找离目标时间戳最近的报文."""
    if not metars:
        return None
    return min(metars, key=lambda r: abs(r.get("obsTime", 0) - target_ts))


def metar_actuals(icao, dates, sunset_hhmm_by_date, max_gap_min=90):
    """按日期算日落时刻 METAR 实况因子. sunset_hhmm_by_date: {date: 'HH:MM' 北京时间}.
    返回 {date: (高云,中云,低云,湿度,降水,AOD, obsTime)}."""
    if not dates:
        return {}
    days = sorted(dates)
    start = datetime.strptime(days[0], "%Y-%m-%d") - timedelta(hours=8)
    end = datetime.strptime(days[-1], "%Y-%m-%d") + timedelta(hours=16)
    metars = fetch_metars(icao, start, end)
    out = {}
    for d in days:
        hhmm = sunset_hhmm_by_date.get(d)
        if not hhmm:
            continue
        local = datetime.strptime(f"{d} {hhmm}", "%Y-%m-%d %H:%M")
        ts = int((local - timedelta(hours=8)).timestamp())
        m = nearest_metar(metars, ts)
        if not m or abs(m.get("obsTime", 0) - ts) > max_gap_min * 60:
            continue
        out[d] = metar_factors(m) + (m["obsTime"],)
    return out
