# 火烧云 (huoshaoyun)

> **本项目无需开发**——已有更完善健全的同类网站：**https://sunsetbot.top/record/custom/** （火烧云分析与记录，含预报/地图/回测混淆矩阵/社区记录库，覆盖主要城市）。本项目定位为私有自用工具（全国监控 + 卫星图验证 + 回测体系）。sunsetbot.top 的完整逆向档案见 [docs/sunsetbot-notes.md](docs/sunsetbot-notes.md)（含架构、数据源、计算方法），供日后复刻参考。

晚霞 / 朝霞指数预报与验证工具。预测未来 7 天每天日落、日出时分的"出霞"质量（0-10 分），事后用近实时分析场和 FY-4B 卫星云图验证，长期积累命中率数据。

数据源全部免费、无需 key：

| 数据 | 来源 | 说明 |
|---|---|---|
| 云量/湿度/降水/能见度 | [Open-Meteo](https://open-meteo.com) 预报 + ERA5 历史 | 全球逐小时, 1940 至今 |
| 气溶胶 AOD | Open-Meteo / CAMS | 决定日落"红不红" |
| 卫星云图 | 中央气象台 FY-4B | 15 分钟一张, 日落时刻实况 |
| 日出日落 | Open-Meteo daily | — |

## 文件

| 文件 | 作用 |
|---|---|
| `forecast.py` | 7 天预报 + 评分 (纯标准库, 零依赖, 带重试) |
| `season.py` | 历史季节分析 (ERA5, 近 5 年) |
| `track.py` | 快照记录 / 实况验证 / 卫星图抓取 / 多城市 |
| `sat.py` | FY-4B 卫星云图抓取 |
| `db.py` | SQLite 数据层 |
| `web.py` | 图表 Web 服务 (ECharts, http://localhost:8000) |
| `index.html` | 前端页面 |
| `.github/workflows/huoshaoyun-daily.yml` | 每日自动流水线 |

## 快速开始

```bash
# 添加城市 (默认不监控任何城市)
python track.py addcity 珠海 22.2707 113.5767

# 记录今日 7 天预报 (全部监控城市)
python track.py snap

# 近实时实况验证 (分析场, 不需要等 ERA5 的 5 天延迟)
python track.py verify

# 抓日落时刻卫星云图 (19:30 后跑, 图是 15 分钟一档)
python track.py sat

# 预报 vs 实况报告
python track.py report

# 启动图表服务, 浏览器自动打开 http://localhost:8000
python web.py
```

数据存放在 `xiat.db` (SQLite) 和 `data/sat/` (卫星图), 两者都被 `.gitignore` 排除, 如需提交用 `git add -f`。

## GitHub Actions 自动流水线

`huoshaoyun-daily` 每天自动执行并**把数据提交回仓库**（云端备份）:

| 时间 (北京时间) | 任务 |
|---|---|
| 17:05 | `track.py snap` 记录预报 |
| 19:35 | `track.py sat` + `track.py verify` |

手动触发 = 全量执行。**注意: workflow 里写死了珠海, 加城市改那行 `addcity`。**

## Linux 部署

本地跑 + git 备份 (GitHub Action 双跑会 push 冲突, 二选一):

```cron
# 17:05 快照 -> 推给 GitHub
5 9 * * *  cd ~/huoshaoyun && git pull --rebase && python3 track.py snap && git add -f xiat.db data/ && git commit -m "data: $(date +\%F)" && git push origin main
# 19:35 卫星图+实况 -> 推给 GitHub
35 11 * * * cd ~/huoshaoyun && git pull --rebase && python3 track.py sat && python3 track.py verify && git add -f xiat.db data/ && git commit -m "data: $(date +\%F)" && git push origin main
```

前提: Linux 上 `git clone` 仓库 + 配 SSH key 免密推送。headless 环境 `web.py` 不会尝试开浏览器, 用 systemd/nohup 常驻即可。

## 评分逻辑

晚霞分 = 云量 + 气溶胶 + 湿度 - 降水惩罚:

- 高云 + 0.7×中云 在日落时段 30~70% 覆盖率最出霞 (满分区), 太晴无霞, 满云压灰
- 低云 >50% 扣分 (遮天)
- AOD 0.1~0.6 红色最佳 (完全无尘的日落是白的), 沙尘暴扣分
- 湿度 ≤60% 加分 (通透)
- 降水概率 >30% 扣分

历史模式 AOD 缺失用中性值; 权重是经验值, 用积累的实况数据校准。

## 注意事项

- 仓库公开时, 预测数据和卫星图全世界可见, 介意请改 private
- 评分 ≥7 不是 100% 保证: 模型预报会随跑次更新, 出门前当天下午重跑一次
- Windows 计划任务: `xiat-snap` (17:00), `xiat-sat` (19:30), 注册表 `HKCU\...\Run` 自启 web

## License

MIT
