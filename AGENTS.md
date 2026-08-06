# AGENTS.md — 火烧云 (huoshaoyun)

晚霞/朝霞指数预报与验证项目。给在这台 Linux 机器上工作的 agent 的项目说明。

## 项目是什么

预测未来 7 天每天日落/日出时分的"出霞质量"（0-10 分），记录预报快照，事后用近实时分析场和 FY-4B 卫星云图验证，长期积累命中率。

## 技术栈

- **Python 3.8+，纯标准库，零外部依赖**（urllib/json/sqlite3/http.server）。不要引入 pip 包。
- SQLite 存储（`xiat.db`），无 ORM。
- 前端是单个 `index.html` + ECharts CDN，由 `web.py` 提供 JSON API。
- 所有脚本输出中文，开头都有 `sys.stdout.reconfigure(encoding="utf-8")`，新文件要保留这个模式。

## 数据源（全部免费免 key）

| 数据 | API | 说明 |
|---|---|---|
| 云量/湿度/降水/日出日落 | `api.open-meteo.com/v1/forecast` | 16 天预报, `past_days` 给近 48h 分析场 |
| 气溶胶 AOD | `air-quality-api.open-meteo.com/v1/air-quality` | CAMS 全球, **只有 5 天预报**, 第 6-7 天是 null, 不能假设有值 |
| 历史 (季节分析) | `archive-api.open-meteo.com/v1/archive` | ERA5, 延迟约 5 天, 已封在 `season.fetch_month` |
| 卫星云图 | `image.nmc.cn` FY-4B 可见光 | 15 分钟一张, **文件名是 UTC 时间**, 中央气象台 |

网络注意:
- `forecast.fetch` 已内置 3 次退避重试 + SSL 验证失败时降级为不验证
- archive-api 的证书在本机有验证问题, 靠降级路径兜底, 正常现象

## 文件职责

| 文件 | 职责 | 关键函数 |
|---|---|---|
| `forecast.py` | 预报拉取 + 评分 | `get_forecast`, `get_verify`, `score_glow`, `build_rows`, `windows_for` |
| `season.py` | 5 年季节分析 (60 次月度请求, 慢) | `analyze`, `fetch_month`, `score_day` |
| `track.py` | CLI 主入口 | `snap_city`, `verify_city`, `sat_city`, `report_city` |
| `sat.py` | FY-4B 抓取 | `fetch_sat` (日落时刻→UTC 15 分钟档) |
| `db.py` | SQLite 层 | `add_city`, `add_snapshot`, `last_preds`, `save_actual`, `save_sat` |
| `web.py` | 图表服务 (8000 端口) | JSON API + 静态文件 |
| `index.html` | 前端 | 4 页签: 未来预报/实况验证/季节分析/追踪复盘 |

## 数据模型 (xiat.db)

- `cities(name, lat, lon, enabled)` — **默认不监控任何城市**, 必须 `addcity` 才跑
- `snapshots(ts, city_id, date, rise_score, set_score, rise_*..., set_*...)` — 存**完整因子**(云量/湿度/降水/AOD), 不存因子只存分 = 改评分公式后历史无法重算, 这是红线
- `actuals(city_id, date, rise_score, set_score, source)` — 实况, source ∈ analysis/era5
- `sat_images(city_id, date, ts, path)` — 卫星图索引, 文件在 `data/sat/`

## 常用命令

```bash
python3 track.py addcity 珠海 22.2707 113.5767   # 加城市 (唯一入口)
python3 track.py snap                            # 记录全部监控城市 7 天预报
python3 track.py sat                             # 抓今天日落时刻卫星图
python3 track.py verify                          # 近实时实况 (分析场)
python3 track.py report                          # 预报 vs 实况
python3 web.py                                   # 图表服务
```

## 评分模型 (score_glow)

输入 (高云, 中云, 低云, 湿度, 降水概率, AOD) → 0-10:
- glow_cloud = 高云 + 0.7×中云; ≤25% 线性爬升(太晴), 30~70% 满分, >70% 往下压(满云灰天)
- 低云 >50% 额外 -1
- AOD: 0.1~0.6 得 2.5 (出红), <0.05 得 0.5 (白日落), >1.5 得 0 (沙尘); **None → 1.5 中性值**
- 湿度: ≤45% 得 2.5, ≤60% 得 2, ≤75% 得 1, 否则 0
- 降水概率: ≥15% 扣 0.5, ≥30% 扣 1.5, ≥50% 扣 2.5
- 实况侧降水用实测 mm 换算: ≥0.2mm → 100%

窗口采样: `windows_for(日出/日落时刻)` 取 [整点-1h, 整点] (分钟≥30 再加整点+1h), 返回完整 ISO 时间戳, 与 hourly 数组按 `YYYY-MM-DDTHH:MM` 精确匹配。

## 定时任务 (Linux 用 crontab)

- 17:05 北京 (09:05 UTC): snap
- 19:35 北京 (11:35 UTC): sat + verify
- GitHub Action 同款已在跑 (`.github/workflows/huoshaoyun-daily.yml`), **本地和 Action 二选一**, 都要跑时 push 前必须 `git pull --rebase`

## 坑

- `xiat.db` 和 `data/` 被 .gitignore 排除, 提交数据必须 `git add -f`
- AOD 第 6-7 天是 null, 前端显示 `--`, 评分走 None 分支, 不要试图填 0
- 第一次跑 `season` 分析要 1-2 分钟 (60 个请求), `web.py` 里有 24h 缓存 (season_cache.json)
- 加新脚本必须 `sys.stdout.reconfigure(encoding="utf-8")`, 否则中文乱码
- 卫星图文件名 UTC 时间 (珠海日落 19:03 北京 = 11:03 UTC, 取 11:00 档)
- 改评分公式 → 快照因子都存着, 可以全量重算, 但公式版本化之前先确认

## 验证改动

```bash
python3 -m py_compile *.py              # 语法
python3 track.py cities                 # db 正常
python3 track.py snap                   # 网络正常 (会真实写库)
python3 web.py &                        # 服务起得来
curl -s localhost:8000/api/forecast?city=珠海 | head -c 200
```
