# -*- coding: utf-8 -*-
"""晚霞 / 朝霞指数预报 — 数据源: Open-Meteo (免费, 免 key)
用法:
    python forecast.py --city 北京 --lat 39.9042 --lon 116.4074 --days 7
"""
import argparse
import json
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from statistics import mean

sys.stdout.reconfigure(encoding="utf-8")

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

HOURLY_VARS = [
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "relative_humidity_2m", "precipitation_probability",
    "visibility", "wind_speed_10m",
]
DAILY_VARS = ["sunrise", "sunset"]


_SSL_BROKEN = False   # 本机证书链坏了时置位, 后续请求直接走不验证路径


def fetch(url, params, timeout=30):
    global _SSL_BROKEN
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "xiat/0.1"})
    last = None
    if not _SSL_BROKEN:
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.load(r)
            except urllib.error.URLError as e:
                last = e
                if isinstance(e.reason, ssl.SSLError):
                    _SSL_BROKEN = True   # 证书链坏了, 记住并直接降级
                    break
                time.sleep(2 * (attempt + 1))      # 网络抖动才退避重试
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.load(r)
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def get_forecast(lat, lon, days, tz="auto"):
    w = fetch(WEATHER_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(HOURLY_VARS), "daily": ",".join(DAILY_VARS),
        "timezone": tz, "forecast_days": days,
    })
    a = fetch(AIR_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": "aerosol_optical_depth", "timezone": tz, "forecast_days": days,
    })
    return w, a


def get_verify(lat, lon, tz="auto"):
    """近实时验证: 取过去 48h 分析场 + 未来 1 天, 含实测降水(用于验证昨日/今日)."""
    w = fetch(WEATHER_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(HOURLY_VARS) + ",precipitation",
        "daily": ",".join(DAILY_VARS),
        "timezone": tz, "past_days": 2, "forecast_days": 1,
    })
    a = fetch(AIR_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": "aerosol_optical_depth", "timezone": tz,
        "past_days": 2, "forecast_days": 1,
    })
    return w, a


def to_index_map(hours, values):
    return {h: v for h, v in zip(hours, values) if v is not None}


def mean_of(indices, mapping, default=None):
    vals = [mapping.get(i) for i in indices if mapping.get(i) is not None]
    return mean(vals) if vals else default


def score_glow(high, mid, low, rh, precip_prob, aod):
    """晚霞/朝霞评分 (0-10). 高云最吃香, 湿度低加分, 气溶胶适中加红, 降水扣分."""
    glow_cloud = (high or 0) + 0.7 * (mid or 0)

    if glow_cloud <= 25:
        cloud = 1 + glow_cloud / 25 * 3      # 太晴 -> 无霞
    elif glow_cloud <= 70:
        cloud = 4 + (glow_cloud - 25) / 45 * 1  # 30~70% -> 满分区
    else:
        cloud = 5 - (glow_cloud - 70) / 30 * 3  # 满云 -> 灰天

    if (low or 0) > 50:
        cloud -= 1                            # 低云遮天

    if aod is None:
        aod_score = 1.5
    elif aod < 0.05:
        aod_score = 0.5                       # 无尘 -> 白日落
    elif aod <= 0.6:
        aod_score = 2.5                       # 适中 -> 火红
    elif aod <= 1.0:
        aod_score = 1.5
    elif aod <= 1.5:
        aod_score = 0.5
    else:
        aod_score = 0.0                       # 沙尘暴

    if rh is None or rh <= 45:
        hum = 2.5
    elif rh <= 60:
        hum = 2.0
    elif rh <= 75:
        hum = 1.0
    else:
        hum = 0.0

    p = precip_prob or 0
    if p >= 50:
        pen = 2.5
    elif p >= 30:
        pen = 1.5
    elif p >= 15:
        pen = 0.5
    else:
        pen = 0.0

    return max(0.0, min(10.0, cloud + aod_score + hum - pen))


def grade(score):
    if score >= 8:
        return "极佳"
    if score >= 6:
        return "佳"
    if score >= 4:
        return "一般"
    if score >= 2:
        return "差"
    return "无霞"


def windows_for(sun_time_str):
    t = datetime.fromisoformat(sun_time_str)
    t_floor = t.replace(minute=0, second=0, microsecond=0)  # 对齐到整点小时桶
    candidates = [t_floor + timedelta(hours=h) for h in (-1, 0)]
    if t.minute >= 30:
        candidates.append(t_floor + timedelta(hours=1))
    return [c.strftime("%Y-%m-%dT%H:%M") for c in candidates], t


def build_rows(w, a, days, tz):
    hourly = w["hourly"]
    times = hourly["time"]
    maps = {v: to_index_map(times, hourly[v]) for v in HOURLY_VARS}
    aod_map = to_index_map(a["hourly"]["time"], a["hourly"]["aerosol_optical_depth"])
    rows = []
    for d in range(days):
        date = (datetime.fromisoformat(times[0]) + timedelta(days=d)).strftime("%m-%d %a")
        rise, set_ = w["daily"]["sunrise"][d], w["daily"]["sunset"][d]
        r_idx, rise_t = windows_for(rise)
        s_idx, set_t = windows_for(set_)

        def factors(idx):
            def rnd(v, d=0):
                if v is None:
                    return None
                r = round(v, d)
                return int(r) if d == 0 else r
            return (
                rnd(mean_of(idx, maps["cloud_cover_high"])),
                rnd(mean_of(idx, maps["cloud_cover_mid"])),
                rnd(mean_of(idx, maps["cloud_cover_low"])),
                rnd(mean_of(idx, maps["relative_humidity_2m"])),
                rnd(mean_of(idx, maps["precipitation_probability"])),
                rnd(mean_of(idx, aod_map), 2),
            )

        hh, hm, hl, hr, hp, ha = factors(r_idx)
        sh, sm, sl, sr, sp, sa = factors(s_idx)
        rows.append({
            "date": date,
            "rise": rise_t.strftime("%H:%M"), "set": set_t.strftime("%H:%M"),
            "rise_score": score_glow(hh, hm, hl, hr, hp, ha),
            "set_score": score_glow(sh, sm, sl, sr, sp, sa),
            "rise_grade": grade(score_glow(hh, hm, hl, hr, hp, ha)),
            "set_grade": grade(score_glow(sh, sm, sl, sr, sp, sa)),
            "rise_cloud": (hh, hm, hl, hr, hp, ha),
            "set_cloud": (sh, sm, sl, sr, sp, sa),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="晚霞/朝霞指数预报 (Open-Meteo 免费数据)")
    ap.add_argument("--city", default="北京", help="城市名, 仅用于显示")
    ap.add_argument("--lat", type=float, default=39.9042)
    ap.add_argument("--lon", type=float, default=116.4074)
    ap.add_argument("--days", type=int, default=7, help="未来天数 (最多 7, 气溶胶数据限制)")
    args = ap.parse_args()
    days = min(max(args.days, 1), 7)

    w, a = get_forecast(args.lat, args.lon, days)
    rows = build_rows(w, a, days, "auto")

    print(f"\n晚霞/朝霞指数预报 · {args.city} ({args.lat}°N, {args.lon}°E)")
    print("数据源: Open-Meteo (云量/湿度/降水/能见度) + CAMS (气溶胶AOD)")
    print("因子列为日落时段数值 (朝霞分独立评估)")
    print("-" * 104)
    print(f"{'日期':<12}{'日出':<7}{'朝霞':<9}{'日落':<7}{'晚霞':<9}"
          f"{'高云':>4}{'中云':>5}{'低云':>5}{'湿度':>5}{'降水%':>6}{'AOD':>5}  {'评价(早/晚)'}")
    print("-" * 104)
    for r in rows:
        sh, sm, sl, sr, sp, sa = r["set_cloud"]

        def cell(v, unit):
            return "--" if v is None else f"{v}{unit}"

        print(f"{r['date']:<12}{r['rise']:<7}{r['rise_score']:.1f}/10"
              f"{' ':<5}{r['set']:<7}{r['set_score']:.1f}/10"
              f"{' ':<5}{cell(sh, '%'):>5}{cell(sm, '%'):>6}{cell(sl, '%'):>6}"
              f"{cell(sr, '%'):>6}{cell(sp, '%'):>6}{cell(sa, ''):>5}  "
              + f"{r['rise_grade']}/{r['set_grade']}")
    print("-" * 104)
    print("评分逻辑: 高云+0.7中云在日落/日出时段 30~70% 最出霞; 湿度≤60% 加分;")
    print("          AOD 0.1~0.6 红色最佳; 降水概率>30% 扣分.")


if __name__ == "__main__":
    sys.exit(main())
