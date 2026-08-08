# -*- coding: utf-8 -*-
"""珠三角 5 年 ERA5 扫描: 找出世纪大烧级晚霞日 (极值尾部).
用法: python scripts/top_glow.py [--years 5]
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from season import fetch_month, score_day  # noqa: E402
from forecast import to_index_map  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "era5_scan")


def cached_month(name, lat, lon, y, m):
    """已算过的月份直接读缓存 (ERA5 是历史数据, 永久有效)."""
    cp = os.path.join(CACHE_DIR, f"{name}_{y}-{m:02d}.json")
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            return json.load(f)
    data = fetch_month(lat, lon, y, m)
    h, dd = data["hourly"], data["daily"]
    maps = {v: to_index_map(h["time"], h[v]) for v in
            ["cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
             "relative_humidity_2m", "precipitation"]}
    sun = {"sunrise": to_index_map(dd["time"], dd["sunrise"]),
           "sunset": to_index_map(dd["time"], dd["sunset"])}
    out = {}
    for d in dd["time"]:
        sc = score_day(d, maps, sun)
        if sc[0] is not None:
            out[d] = [round(sc[1], 2), round(sc[0], 2)]   # [朝霞, 晚霞]
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def scan_city(name, lat, lon, years):
    days = []
    for y in range(datetime.now().year - years, datetime.now().year):
        for m in range(1, 13):
            try:
                out = cached_month(name, lat, lon, y, m)
            except Exception:
                continue
            days.extend((s[1], d) for d, s in out.items())
            print(f"  [{name}] {y}-{m:02d}: {len(out)} 天")
    days.sort(reverse=True)
    print(f"[done] {name}: {len(days)} 天, TOP "
          + ", ".join(f"{d} {s:.1f}" for s, d in days[:3]))
    return days

CITIES = [
    ("珠海", 22.2707, 113.5767),
    ("广州", 23.1291, 113.2644),
    ("深圳", 22.5431, 114.0579),
    ("佛山", 23.0218, 113.1219),
    ("东莞", 23.0207, 113.7518),
    ("中山", 22.5176, 113.3928),
    ("惠州", 23.1115, 114.4162),
    ("江门", 22.5791, 113.0815),
    ("肇庆", 23.0471, 112.4724),
]


def main():
    years = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--years" else 5
    all_days = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(scan_city, name, lat, lon, years): name
                   for name, lat, lon in CITIES}
        for fut in futures:
            for s, d in fut.result():
                all_days.append((s, d, futures[fut]))

    all_days.sort(reverse=True)
    total = len(all_days)
    n9 = sum(1 for s, *_ in all_days if s >= 9.0)
    n85 = sum(1 for s, *_ in all_days if s >= 8.5)
    print(f"\n珠三角 9 城 {years} 年共 {total} 天 (日落)")
    print(f"≥9.0 (世纪大烧级): {n9} 天 ({n9/total*100:.2f}%)  |  "
          f"≥8.5 (大烧级): {n85} 天 ({n85/total*100:.2f}%)")
    print("\nTOP 15 (跨城市):")
    for s, d, name in all_days[:15]:
        print(f"  {d} {name}  晚霞 {s:.1f}/10")


if __name__ == "__main__":
    main()
