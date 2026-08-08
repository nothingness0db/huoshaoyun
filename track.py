# -*- coding: utf-8 -*-
"""晚霞预报追踪 — SQLite 存储, 多城市 (默认不监控任何城市)
用法:
    python track.py cities                       # 查看城市列表
    python track.py addcity 深圳 22.5431 114.0579  # 添加并启用监控
    python track.py rmcity 深圳                    # 移除城市
    python track.py snap [--city 珠海]             # 记录预报 (默认全部已启用城市)
    python track.py verify [--city 珠海]           # 用近实时分析场补实况
    python track.py sat [--date 2026-08-06]        # 抓日落时刻卫星云图
    python track.py report [--city 珠海]           # 预报 vs 实况
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import sat  # noqa: E402
from forecast import (  # noqa: E402
    get_forecast, get_verify, mean_of, score_glow, to_index_map, windows_for,
)


def snap_city(city, days=7):
    w, a = get_forecast(city["lat"], city["lon"], days)
    dates = [w["daily"]["sunset"][i][:10] for i in range(days)]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, d in enumerate(dates):
        rise_t = w["daily"]["sunrise"][i]
        set_t = w["daily"]["sunset"][i]
        r_idx, _ = windows_for(rise_t)
        s_idx, _ = windows_for(set_t)

        def factors(idx):
            g = {v: mean_of(idx, m) for v, m in
                 {v: to_index_map(w["hourly"]["time"], w["hourly"][v])
                  for v in ["cloud_cover_low", "cloud_cover_mid",
                            "cloud_cover_high", "relative_humidity_2m",
                            "precipitation_probability"]}.items()}
            aod = mean_of(idx, to_index_map(a["hourly"]["time"],
                                            a["hourly"]["aerosol_optical_depth"]))
            return (g["cloud_cover_high"], g["cloud_cover_mid"], g["cloud_cover_low"],
                    g["relative_humidity_2m"], g["precipitation_probability"], aod)

        def score(idx):
            f = factors(idx)
            return score_glow(f[0], f[1], f[2], f[3], f[4], f[5])

        r = {"rise_score": score(r_idx), "set_score": score(s_idx),
             "rise_cloud": factors(r_idx), "set_cloud": factors(s_idx)}
        db.add_snapshot(city["id"], ts, d, r)
    print(f"[snap] {city['name']} {ts} 记录 {days} 天")


def verify_city(city):
    w, a = get_verify(city["lat"], city["lon"])
    h = w["hourly"]
    maps = {v: to_index_map(h["time"], h[v]) for v in
            ["cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
             "relative_humidity_2m", "precipitation_probability"]}
    maps["precipitation"] = to_index_map(h["time"], h["precipitation"])
    aod_map = to_index_map(a["hourly"]["time"], a["hourly"]["aerosol_optical_depth"])

    def score(idx):
        g = {v: mean_of(idx, maps[v]) for v in maps}
        p = mean_of(idx, maps["precipitation"])
        pp = 0.0 if (p or 0) < 0.2 else 100.0
        return score_glow(g["cloud_cover_high"], g["cloud_cover_mid"],
                          g["cloud_cover_low"], g["relative_humidity_2m"],
                          pp, mean_of(idx, aod_map))

    n = 0
    for i, d in enumerate(w["daily"]["sunset"]):
        date = d[:10]
        rise = score(windows_for(w["daily"]["sunrise"][i])[0])
        set_ = score(windows_for(w["daily"]["sunset"][i])[0])
        db.save_actual(city["id"], date, rise, set_, "analysis")
        n += 1
    print(f"[verify] {city['name']} 补实况 {n} 天 (近实时分析场)")


def sat_city(city, date):
    from forecast import fetch
    w = fetch("https://api.open-meteo.com/v1/forecast", {
        "latitude": city["lat"], "longitude": city["lon"],
        "daily": "sunset", "timezone": "auto",
        "start_date": date, "end_date": date,
    })
    sunset = w["daily"]["sunset"][0][11:16]
    ts, path = sat.fetch_sat(date, sunset)
    db.save_sat(city["id"], date, ts, path)
    print(f"[sat] {city['name']} {date} 日落 {sunset} -> {os.path.basename(path)} ({ts})")


def metar_city(city, date):
    """用机场 METAR 观测报算日落时刻实况分 (真观测, 对比 analysis 场)."""
    import metar
    icaos = metar.ICAO.get(city["name"], [])
    from forecast import fetch
    w = fetch("https://api.open-meteo.com/v1/forecast", {
        "latitude": city["lat"], "longitude": city["lon"],
        "daily": "sunset", "timezone": "auto",
        "start_date": date, "end_date": date,
    })
    sunset = w["daily"]["sunset"][0]
    icao_used = None
    for icao in icaos:
        factors = metar.metar_actuals(icao, [date], {date: sunset[11:16]})
        if factors:
            icao_used = icao
            break
    if not icao_used:
        print(f"[metar] {city['name']} {date} 日落 {sunset[11:16]} 附近无观测报"
              f" (候选机场 {icaos})")
        return
    high, mid, low, rh, pp, aod, ts = factors[date]
    score = score_glow(high, mid, low, rh, pp, aod)
    ts_local = datetime.utcfromtimestamp(ts) + timedelta(hours=8)
    actual = db.get_actuals(city["id"]).get(date)
    comp = f"  vs 分析场实况 {actual['set']:.1f}" if actual else ""
    print(f"[metar] {city['name']} {date} 日落 {sunset[11:16]} ({icao_used}) "
          f"观测时刻 {ts_local:%H:%M} 高{high}% 中{mid}% 低{low}% "
          f"湿度{rh}% 降水{pp}%  -> METAR 实况分 {score:.1f}{comp}")


def report_city(city):
    actuals = db.get_actuals(city["id"])
    hist = db.snap_history(city["id"])
    rows = [{"date": d, **hist[d], "actual": actuals[d]["set"]}
            for d in sorted(actuals) if d in hist]
    print(f"\n预报 vs 实况 · {city['name']}  (样本 {len(rows)} 天)")
    print("-" * 52)
    print(f"{'日期':<12}{'首报':<8}{'末报':<8}{'实况':<8}  命中(≥7)")
    print("-" * 52)
    p7, hits = 0, 0
    for r in rows:
        is7 = r["first"] >= 7 or r["last"] >= 7
        if is7:
            p7 += 1
            if r["actual"] >= 6:
                hits += 1
        hit = "中" if is7 and r["actual"] >= 6 else ("漏" if r["actual"] >= 6 and not is7 else "")
        print(f"{r['date']:<12}{r['first']:<8.1f}{r['last']:<8.1f}{r['actual']:<8.1f}  {hit}")
    if rows:
        mae1 = sum(abs(r["first"] - r["actual"]) for r in rows) / len(rows)
        mae2 = sum(abs(r["last"] - r["actual"]) for r in rows) / len(rows)
        print(f"MAE: 首报 {mae1:.2f}  末报 {mae2:.2f}", end="  ")
        if p7:
            print(f"≥7命中率 {hits}/{p7} = {hits/p7*100:.0f}%")
        else:
            print()


def main():
    ap = argparse.ArgumentParser(description="晚霞预报追踪 (SQLite)")
    ap.add_argument("cmd", choices=["cities", "addcity", "rmcity",
                                    "snap", "verify", "sat", "metar", "report"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--city", default=None)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    db.init_db()
    migrated = db.migrate_legacy()
    if migrated:
        print(f"[迁移] 旧 track_log 导入 {migrated} 条快照 (珠海已启用)")

    if args.cmd == "cities":
        for c in db.list_cities(enabled_only=False):
            tag = "监控中" if c["enabled"] else "已停用"
            print(f"  {c['name']} ({c['lat']}, {c['lon']}) [{tag}]")
        return
    if args.cmd == "addcity":
        if len(args.args) < 3:
            print("用法: track.py addcity 名称 纬度 经度")
            return
        name, lat, lon = args.args[0], float(args.args[1]), float(args.args[2])
        db.add_city(name, lat, lon, 1)
        print(f"[addcity] {name} 已加入并启用监控")
        return
    if args.cmd == "rmcity":
        if not args.args:
            print("用法: track.py rmcity 名称")
            return
        db.remove_city(args.args[0])
        print(f"[rmcity] {args.args[0]} 已移除")
        return

    cities = ([c for c in db.list_cities() if c["name"] == args.city]
              if args.city else db.list_cities())
    if not cities:
        print("没有监控中的城市. 先执行: python track.py addcity 城市名 纬度 经度")
        return

    for c in cities:
        if args.cmd == "snap":
            snap_city(c)
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if not any(True for _ in db.last_preds(c["id"], [yesterday])):
                print(f"  ! 警告: {c['name']} 昨天 {yesterday} 没记录预报 (可能漏跑)")
        elif args.cmd == "verify":
            verify_city(c)
        elif args.cmd == "sat":
            date = args.date or datetime.now().strftime("%Y-%m-%d")
            sat_city(c, date)
        elif args.cmd == "metar":
            date = args.date or datetime.now().strftime("%Y-%m-%d")
            metar_city(c, date)
        elif args.cmd == "report":
            report_city(c)


if __name__ == "__main__":
    sys.exit(main())
