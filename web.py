# -*- coding: utf-8 -*-
"""晚霞预报图表服务 — 启动: python web.py (自动开浏览器)"""
import json
import os
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import mean

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import sat  # noqa: E402
from forecast import (  # noqa: E402
    HOURLY_VARS, build_rows, get_forecast, get_verify, mean_of, score_glow,
    to_index_map, windows_for,
)
from season import analyze  # noqa: E402

PORT = 8000
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "season_cache.json")
CACHE_TTL = 24 * 3600


def load_season(lat, lon, years=5):
    key = f"{lat:.4f},{lon:.4f}"
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("key") == key and time.time() - c.get("ts", 0) < CACHE_TTL:
            return c["data"]
    by_month, best = analyze(lat, lon, years)
    months = [{"month": m, "avg": round(mean(s), 2),
               "pct6": round(sum(1 for x in s if x >= 6) / len(s) * 100),
               "pct8": round(sum(1 for x in s if x >= 8) / len(s) * 100)}
              for m, s in sorted(by_month.items())]
    data = {"months": months,
            "top": [{"date": d, "score": round(s, 1), "rise": round(r, 1)}
                    for s, d, r in sorted(best, key=lambda x: -x[0])[:10]],
            "total_days": sum(len(v) for v in by_month.values())}
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump({"key": key, "ts": time.time(), "data": data}, f, ensure_ascii=False)
    return data


def verify_scores(city):
    w, a = get_verify(city["lat"], city["lon"])
    h = w["hourly"]
    maps = {v: to_index_map(h["time"], h[v]) for v in HOURLY_VARS}
    maps["precipitation"] = to_index_map(h["time"], h["precipitation"])
    aod_map = to_index_map(a["hourly"]["time"], a["hourly"]["aerosol_optical_depth"])
    dates = [d[:10] for d in w["daily"]["sunset"]]
    preds = db.last_preds(city["id"], dates)

    def score(idx):
        g = {v: mean_of(idx, maps[v]) for v in HOURLY_VARS}
        p = mean_of(idx, maps["precipitation"])
        pp = 0.0 if (p or 0) < 0.2 else 100.0
        return score_glow(g["cloud_cover_high"], g["cloud_cover_mid"],
                          g["cloud_cover_low"], g["relative_humidity_2m"],
                          pp, mean_of(idx, aod_map))

    out = []
    for i, d in enumerate(dates):
        rise = score(windows_for(w["daily"]["sunrise"][i])[0])
        set_ = score(windows_for(w["daily"]["sunset"][i])[0])
        pred = preds.get(d)
        out.append({"date": d,
                    "pred_set": round(pred["set"], 1) if pred else None,
                    "actual_set": round(set_, 1), "actual_rise": round(rise, 1)})
    return out


def track_rows(city):
    actuals = db.get_actuals(city["id"])
    hist = db.snap_history(city["id"])
    rows = [{"date": d, **hist[d], "actual": actuals[d]["set"]}
            for d in sorted(actuals) if d in hist]
    n = len(rows)
    if n:
        mae1 = sum(abs(r["first"] - r["actual"]) for r in rows) / n
        mae2 = sum(abs(r["last"] - r["actual"]) for r in rows) / n
        p7 = [r for r in rows if r["first"] >= 7 or r["last"] >= 7]
        hits = sum(1 for r in p7 if r["actual"] >= 6)
        stats = {"n": n, "mae_first": round(mae1, 2), "mae_last": round(mae2, 2),
                 "pred7": len(p7), "hit7": hits,
                 "hit_rate": round(hits / len(p7) * 100) if p7 else None}
    else:
        stats = {"n": 0}
    return {"rows": rows, "stats": stats}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def city_from_qs(self, qs):
        name = qs.get("city", [None])[0]
        if name:
            return db.get_city(name)
        cities = db.list_cities()
        return cities[0] if cities else None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path == "/":
            self.serve_file("index.html", "text/html; charset=utf-8")
        elif path.startswith("/img/"):
            rel = urllib.parse.unquote(path[5:])
            full = os.path.join(HERE, "data", "sat", rel)
            if os.path.exists(full):
                self.serve_file(full, "image/jpeg", binary=True)
            else:
                self.send_error(404)
        elif path == "/api/cities":
            self.send_json({"cities": db.list_cities()})
        elif path == "/api/forecast":
            city = self.city_from_qs(qs)
            if not city:
                self.send_json({"dates": [], "rise": [], "set": []})
                return
            days = int(qs.get("days", [7])[0])
            w, a = get_forecast(city["lat"], city["lon"], days)
            rows = build_rows(w, a, days, "auto")
            dates = [w["daily"]["sunset"][i][:10] for i in range(days)]
            self.send_json({
                "dates": dates,
                "rise": [r["rise_score"] for r in rows],
                "set": [r["set_score"] for r in rows],
                "rise_grade": [r["rise_grade"] for r in rows],
                "set_grade": [r["set_grade"] for r in rows],
                "rise_time": [r["rise"] for r in rows],
                "set_time": [r["set"] for r in rows],
                "factors": [r["set_cloud"] for r in rows],
            })
        elif path == "/api/verify":
            city = self.city_from_qs(qs)
            if not city:
                self.send_json({"rows": []})
                return
            rows = verify_scores(city)
            s = db.get_sat(city["id"])
            self.send_json({"rows": rows,
                            "sat": {"date": s["date"], "ts": s["ts"],
                                    "url": sat.satellite_static(
                                        os.path.relpath(s["path"], sat.SAT_DIR))}
                            if s else None})
        elif path == "/api/season":
            city = self.city_from_qs(qs)
            if not city:
                self.send_json({"months": [], "top": []})
                return
            self.send_json(load_season(city["lat"], city["lon"]))
        elif path == "/api/track":
            city = self.city_from_qs(qs)
            if not city:
                self.send_json({"rows": [], "stats": {"n": 0}})
                return
            self.send_json(track_rows(city))
        else:
            self.send_error(404)

    def serve_file(self, name, ctype, binary=False):
        path = name if os.path.isabs(name) else os.path.join(HERE, name)
        if not os.path.exists(path):
            self.send_error(404)
            return
        mode = "rb" if binary else "r"
        with open(path, mode, encoding=None if binary else "utf-8") as f:
            body = f.read()
        if not binary:
            body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    db.init_db()
    print(f"晚霞图表服务: http://localhost:{PORT}")
    if os.name == "nt" or os.environ.get("DISPLAY"):
        try:
            webbrowser.open(f"http://localhost:{PORT}")
        except Exception:
            pass
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
