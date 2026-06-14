# 01 · 项目概览

## 项目目标

构建一个**A 股周频小市值 + 基本面趋势策略**的端到端流水线，包括：

1. **数据采集**：自动拉取 A 股清单、个股日线、年度财务指标、流通市值。
2. **股票池筛选**：剔除高风险板块（创业板、科创板、北交所），保留主板可投资标的。
3. **回测引擎**：在历史数据上模拟"周四买入、下周三卖出"的轮动策略。
4. **实时选股**：在交易日开盘前给出当日候选股列表。
5. **绩效评估**：累计收益、年化、最大回撤、夏普比率，并画资金曲线对比沪深 300 基准。

## 核心策略一句话

> 每周三收盘后基于"主板 + EPS>0 + ROE>10% + 流通市值升序"挑选 5 只股票，周四开盘等权买入（100 股取整），下周三按收盘价卖出（涨停一字板除外）。

## 技术栈

- **Python 3.12**（内核 `quant`，见 `main.ipynb` 的 `kernelspec`）
- **数据源**：[AKShare](https://akshare.akfamily.xyz/) 东方财富接口
  - `stock_zh_a_spot_em` — 沪深京 A 股实时快照
  - `stock_zh_a_hist` — 个股日 K 线（前/后/不复权）
  - `stock_zh_a_hist_min_em` — 个股分钟 K 线（5 分钟 / 1 分钟）
  - `stock_financial_analysis_indicator_em` — 主要财务指标（按报告期）
  - `stock_value_em` — 历史市值数据
  - `stock_zh_index_daily` — 指数行情（沪深 300 等）
- **数据处理**：`pandas` / `numpy`
- **可视化**：`matplotlib`（中文字体 SimHei / Microsoft YaHei / Noto Sans CJK SC）
- **进度条**：`tqdm`

## 依赖安装

```bash
pip install akshare pandas numpy matplotlib tqdm
```

> AKShare 在中国大陆以外地区可能需要配置代理；东财接口 `stock_zh_a_spot_em` 连接不稳定，建议在网络通畅时段运行并做好断点续传。

## 端到端运行顺序

```
1.  data:  code/main.ipynb
    ├─ 阶段 A：拉 A 股全量快照 → stock_zh_a_spot_em.csv
    ├─ 阶段 B：过滤板块 / NaN → stock_zh_a_spot_em_filtered.csv
    ├─ 阶段 C：给代码加 .SZ/.SH/.BJ 后缀 → ..._with_suffix.csv
    ├─ 阶段 D：逐只下载日线 → data/stock_daily_data/*.csv
    ├─ 阶段 E：合并日线 → all_stocks_daily.csv（~11.9M 行）
    └─ 阶段 F：合并年报 EPS/ROE + 流通市值 → A股_日行情_年报_流通市值.csv

2.  backtest:  code/选股.ipynb
    ├─ 读统一底表 (2018-01-01 起)
    ├─ 逐日 groupby，撮合周三卖出 / 周四买入
    ├─ 计算日收益率、累计、最大回撤、夏普
    └─ 画双 y 轴资金曲线，保存 trading_records.csv

3.  live:  code/未来选股.ipynb
    ├─ 读带后缀代码表
    ├─ 对单只股票实时拉财务 / 行情 / 流通市值（带重试）
    └─ 输出当日 Top N 候选股
```

## 关键约定

- **股票代码**：6 位字符串（保留前导 0），带后缀形如 `000001.SZ`（深市）、`600000.SH`（沪市）、`830xxx.BJ`（北交所）。
- **日期**：pandas `datetime64[ns]`，字符串格式 `YYYY-MM-DD`。
- **数据频率**：日频，少数分钟频（仅 `未来选股.ipynb` 的 `load_daily_price` 用到 5 分钟 K 线）。
- **回测起止**：`2018-01-01` 至 `2025-12-31`（`main.ipynb` 拉数据范围）。

## 命名规范

| 命名 | 含义 |
| --- | --- |
| `代码` / `代码_full` | 6 位代码 / 带后缀代码 |
| `股票代码` | `all_stocks_daily.csv` 内的 6 位代码列 |
| `EPSJB` | 基本每股收益（元，Basic EPS） |
| `ROEJQ` | 净资产收益率（加权，%） |
| `流通市值` | 当日流通市值（元） |
| `NOTICE_DATE` | 财报公告日 |
| `prev_close` | 上一交易日收盘价（回测内衍生） |
| `is_limit_up` / `is_limit_down` | 涨停 / 跌停标记（10% 阈值） |

## 风险提示

- 策略对小市值因子依赖较重，A 股自 2017 年后小市值效应已显著衰减。
- 回测**未考虑**：停牌、涨跌停一字板买入失败、滑点、ST 股 5% 阈值、印花税减半政策、注册制新股波动等。
- 数据来自第三方抓取接口，存在**字段缺失 / 接口变更 / 退市股残留**风险，使用前应做数据校验。
