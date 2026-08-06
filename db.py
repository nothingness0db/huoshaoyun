# -*- coding: utf-8 -*-
"""SQLite 数据层 — 城市 / 预报快照(含完整因子) / 实况 / 卫星图记录"""
import json
import os
import sqlite3
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiat.db")
LEGACY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "track_log.json")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS cities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            added_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            city_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            rise_score REAL, set_score REAL,
            rise_high INTEGER, rise_mid INTEGER, rise_low INTEGER,
            rise_rh INTEGER, rise_precip INTEGER, rise_aod REAL,
            set_high INTEGER, set_mid INTEGER, set_low INTEGER,
            set_rh INTEGER, set_precip INTEGER, set_aod REAL,
            FOREIGN KEY(city_id) REFERENCES cities(id));
        CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(city_id, date);
        CREATE TABLE IF NOT EXISTS actuals(
            city_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            rise_score REAL, set_score REAL,
            source TEXT NOT NULL,
            PRIMARY KEY(city_id, date));
        CREATE TABLE IF NOT EXISTS sat_images(
            city_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            ts TEXT NOT NULL,
            path TEXT NOT NULL,
            PRIMARY KEY(city_id, date));
        """)


def migrate_legacy():
    """从旧 track_log.json 一次性导入 (珠海, 已启用)."""
    if not os.path.exists(LEGACY):
        return 0
    with conn() as c:
        if c.execute("SELECT COUNT(*) FROM cities").fetchone()[0] > 0:
            return 0
        with open(LEGACY, encoding="utf-8") as f:
            log = json.load(f)
        meta = log.get("city", {})
        if not meta:
            os.rename(LEGACY, LEGACY + ".old")
            return 0
        c.execute("INSERT OR IGNORE INTO cities(name, lat, lon, enabled, added_at)"
                  " VALUES(?,?,?,1,?)",
                  (meta.get("name", "珠海"), meta["lat"], meta["lon"],
                   datetime.now().strftime("%Y-%m-%d %H:%M")))
        cid = c.execute("SELECT id FROM cities WHERE name=?",
                        (meta.get("name", "珠海"),)).fetchone()["id"]
        n = 0
        for s in log.get("snapshots", []):
            for date, p in s["pred"].items():
                c.execute("INSERT INTO snapshots(ts, city_id, date, rise_score, set_score)"
                          " VALUES(?,?,?,?,?)",
                          (s["ts"], cid, date, p.get("rise"), p.get("set")))
                n += 1
        for date, a in log.get("actuals", {}).items():
            c.execute("INSERT OR REPLACE INTO actuals(city_id, date, rise_score, set_score, source)"
                      " VALUES(?,?,?,?,?)",
                      (cid, date, a.get("rise"), a.get("set"), "era5"))
        os.rename(LEGACY, LEGACY + ".old")
        return n


# ---------- 城市 ----------

def list_cities(enabled_only=True):
    with conn() as c:
        if enabled_only:
            rows = c.execute("SELECT * FROM cities WHERE enabled=1 ORDER BY id").fetchall()
        else:
            rows = c.execute("SELECT * FROM cities ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_city(name):
    with conn() as c:
        r = c.execute("SELECT * FROM cities WHERE name=?", (name,)).fetchone()
    return dict(r) if r else None


def add_city(name, lat, lon, enabled=1):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO cities(name, lat, lon, enabled, added_at)"
                  " VALUES(?,?,?,?,?)",
                  (name, lat, lon, enabled, datetime.now().strftime("%Y-%m-%d %H:%M")))


def remove_city(name):
    with conn() as c:
        c.execute("DELETE FROM cities WHERE name=?", (name,))


# ---------- 快照 ----------

def add_snapshot(city_id, ts, date, r):
    with conn() as c:
        c.execute("""INSERT INTO snapshots(
            ts, city_id, date, rise_score, set_score,
            rise_high, rise_mid, rise_low, rise_rh, rise_precip, rise_aod,
            set_high, set_mid, set_low, set_rh, set_precip, set_aod)
            VALUES(?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?)""",
            (ts, city_id, date,
             r["rise_score"], r["set_score"],
             *r["rise_cloud"], *r["set_cloud"]))


def last_preds(city_id, dates):
    """每个日期最近一次预报分数 {date: {rise, set}}."""
    with conn() as c:
        rows = c.execute("""
            SELECT s.date, s.rise_score, s.set_score
            FROM snapshots s
            JOIN (SELECT date, MAX(ts) ts FROM snapshots
                  WHERE city_id=? AND date IN ({})
                  GROUP BY date) m
            ON s.city_id=? AND s.date=m.date AND s.ts=m.ts
            """.format(",".join("?" * len(dates))), [city_id, *dates, city_id]).fetchall()
    return {r["date"]: {"rise": r["rise_score"], "set": r["set_score"]} for r in rows}


def snap_history(city_id):
    """按日期聚合: 首报/末报 {date: {first, last}}."""
    with conn() as c:
        rows = c.execute("""
            SELECT date, MIN(ts) ts1, MAX(ts) ts2
            FROM snapshots WHERE city_id=? GROUP BY date""", (city_id,)).fetchall()
        out = {}
        for r in rows:
            d = r["date"]
            f = c.execute("SELECT set_score FROM snapshots WHERE city_id=? AND date=? AND ts=?",
                          (city_id, d, r["ts1"])).fetchone()
            l = c.execute("SELECT set_score FROM snapshots WHERE city_id=? AND date=? AND ts=?",
                          (city_id, d, r["ts2"])).fetchone()
            out[d] = {"first": f["set_score"], "last": l["set_score"]}
    return out


def missing_dates(city_id, since, until):
    """日期范围内没记录过快照的日期 (补漏检测)."""
    with conn() as c:
        rows = c.execute("SELECT DISTINCT date FROM snapshots"
                         " WHERE city_id=? AND date BETWEEN ? AND ?",
                         (city_id, since, until)).fetchall()
    return [r["date"] for r in rows]


# ---------- 实况 ----------

def get_actuals(city_id):
    with conn() as c:
        rows = c.execute("SELECT * FROM actuals WHERE city_id=?", (city_id,)).fetchall()
    return {r["date"]: {"rise": r["rise_score"], "set": r["set_score"],
                        "source": r["source"]} for r in rows}


def save_actual(city_id, date, rise, set_, source):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO actuals(city_id, date, rise_score, set_score, source)"
                  " VALUES(?,?,?,?,?)", (city_id, date, rise, set_, source))


# ---------- 卫星图 ----------

def save_sat(city_id, date, ts, path):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO sat_images(city_id, date, ts, path)"
                  " VALUES(?,?,?,?)", (city_id, date, ts, path))


def get_sat(city_id, date=None):
    with conn() as c:
        if date:
            r = c.execute("SELECT * FROM sat_images WHERE city_id=? AND date=?",
                          (city_id, date)).fetchone()
        else:
            r = c.execute("SELECT * FROM sat_images WHERE city_id=? ORDER BY date DESC LIMIT 1",
                          (city_id,)).fetchone()
    return dict(r) if r else None
