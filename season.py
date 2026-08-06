# -*- coding: utf-8 -*-
"""历史晚霞/朝霞季节分析 — 数据源: Open-Meteo Historical (ERA5 再分析, 1940 至今)
用法: python season.py --city 珠海 --lat 22.2707 --lon 113.5767 --years 5
"""
import argparse
import calendar
import sys
import urllib.parse
from collections import defaultdict
from statistics import mean

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __import__("os").path.dirname(__file__))
from forecast import (  # noqa: E402
    DAILY_VARS, HOURLY_VARS, fetch, score_glow, to_index_map, windows_for,
)

HIST_URL = "https://archive-api.open-meteo.com/v1/archive"
HIST_VARS = ["cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
             "relative_humidity_2m", "precipitation"]


def fetch_month(lat, lon, year, month):
    _, last = calendar.monthrange(year, month)
    start, end = f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last}"
    return fetch(HIST_URL, {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "hourly": ",".join(HIST_VARS),
        "daily": ",".join(DAILY_VARS),
        "timezone": "auto",
    })


def score_day(d, maps, daily_sun):
    def score_at(sun_str, aod=None):
        idx, _ = windows_for(sun_str)
        high = mean([maps["cloud_cover_high"].get(i) for i in idx
                     if maps["cloud_cover_high"].get(i) is not None])
        mid = mean([maps["cloud_cover_mid"].get(i) for i in idx
                    if maps["cloud_cover_mid"].get(i) is not None])
        low = mean([maps["cloud_cover_low"].get(i) for i in idx
                    if maps["cloud_cover_low"].get(i) is not None])
        rh = mean([maps["relative_humidity_2m"].get(i) for i in idx
                   if maps["relative_humidity_2m"].get(i) is not None])
        p = mean([maps["precipitation"].get(i) for i in idx
                  if maps["precipitation"].get(i) is not None])
        if high is None:
            return None
        precip_prob = 0.0 if (p or 0) < 0.2 else 100.0
        return score_glow(high, mid, low, rh, precip_prob, aod)

    sunrise = daily_sun.get("sunrise", {}).get(d)
    sunset = daily_sun.get("sunset", {}).get(d)
    return score_at(sunset), score_at(sunrise)


def analyze(lat, lon, years):
    by_month = defaultdict(list)
    best_days = []
    for y in range(2026 - years, 2026):
        for m in range(1, 13):
            d = fetch_month(lat, lon, y, m)
            h, dd = d["hourly"], d["daily"]
            maps = {v: to_index_map(h["time"], h[v]) for v in HIST_VARS}
            sun = {"sunrise": to_index_map(dd["time"], dd["sunrise"]),
                   "sunset": to_index_map(dd["time"], dd["sunset"])}
            for day in dd["time"]:
                sc = score_day(day, maps, sun)
                if sc[0] is None:
                    continue
                by_month[day[5:7]].append(sc[0])
                best_days.append((sc[0], day, sc[1]))
    return by_month, best_days


def main():
    ap = argparse.ArgumentParser(description="历史晚霞季节分析 (ERA5 再分析)")
    ap.add_argument("--city", default="珠海")
    ap.add_argument("--lat", type=float, default=22.2707)
    ap.add_argument("--lon", type=float, default=113.5767)
    ap.add_argument("--years", type=int, default=5, help="回溯年数")
    args = ap.parse_args()

    by_month, best = analyze(args.lat, args.lon, args.years)
    total = sum(len(v) for v in by_month.values())

    print(f"\n{args.city} 历史晚霞季节分析 (近 {args.years} 年, 共 {total} 天, 数据: ERA5)")
    print("-" * 56)
    print(f"{'月份':<8}{'平均晚霞分':<12}{'≥6分占比':<12}{'≥8分占比':<10}")
    print("-" * 56)
    rank = sorted(by_month.items(), key=lambda kv: mean(kv[1]), reverse=True)
    for m, scores in rank:
        pct6 = sum(1 for s in scores if s >= 6) / len(scores) * 100
        pct8 = sum(1 for s in scores if s >= 8) / len(scores) * 100
        print(f"{m}月{'':<6}{mean(scores):.2f}{'':<8}{pct6:.0f}%{'':<8}{pct8:.0f}%")
    print("-" * 56)

    best.sort(key=lambda x: x[0], reverse=True)
    print("\n历史最佳晚霞日 TOP 10:")
    for s, day, _ in best[:10]:
        print(f"  {day}  晚霞 {s:.1f}/10")

    m1, s1 = rank[0]
    print(f"\n结论: {args.city} 的晚霞黄金季是 {m1} 月 (平均 {mean(s1):.1f}/10)")


if __name__ == "__main__":
    sys.exit(main())
