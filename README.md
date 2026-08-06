# 火烧云 (huoshaoyun)

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
| `forecast.py` | 7 天预报 + 评分 (纯标准库, 零依赖) |
| `season.py` | 历史季节分析 (ERA5, 5 年) |
| `track.py` | 快照记录 / 实况验证 / 卫星图抓取 / 多城市 |
| `sat.py` | FY-4B 卫星云图抓取 |
| `db.py` | SQLite 数据层 |
| `web.py` | 图表 Web 服务 (ECharts) |
| `index.html` | 前端页面 |

## 快速开始

```bash
# 添加城市 (默认不监控任何城市)
python track.py addcity 珠海 22.2707 113.5767

# 记录今日 7 天预报 (全部监控城市)
python track.py snap

# 近实时实况验证 (分析场, 非 ERA5 无需等 5 天)
python track.py verify

# 抓日落时刻卫星云图
python track.py sat

# 预报 vs 实况报告
python track.py report

# 启动图表服务 http://localhost:8000
python web.py
```

## Linux 定时任务

```cron
# 每天 17:00 (北京时间) 记录预报
0 9 * * * cd /path/to/huoshaoyun && python3 track.py snap
# 每天 19:30 抓卫星云图
30 11 * * * cd /path/to/huoshaoyun && python3 track.py sat
# 图表服务开机自启 (systemd 或 nohup)
```

Windows 上则用计划任务: `xiat-snap` (17:00), `xiat-sat` (19:30), 注册表 `HKCU\...\Run` 自启 web 服务。

## 评分逻辑

晚霞分 = 云量 + 气溶胶 + 湿度 - 降水惩罚：

- 高云 + 0.7×中云 在日落时段 30~70% 覆盖率最出霞 (满分区), 太晴无霞, 满云压灰
- 低云 >50% 扣分 (遮天)
- AOD 0.1~0.6 红色最佳 (完全无尘的日落是白的), 沙尘暴扣分
- 湿度 ≤60% 加分 (通透)
- 降水概率 >30% 扣分

历史模式 AOD 缺失用中性值; 评分权重是经验值, 可用积累的实况数据校准。

## License

MIT
