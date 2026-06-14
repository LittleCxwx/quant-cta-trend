# 06 · 数据字典

> 本项目所有数据文件均由 `main.ipynb` 流水线生成，或由 akshare 实时拉取后落盘。

## 6.1 `data/stock_zh_a_spot_em.csv`

**来源**：`ak.stock_zh_a_spot_em()`（东方财富沪深京 A 股实时快照）
**记录数**：~5790 行 × 23 列
**生成频次**：低频（连接不稳定，作者建议成功后只跑一次）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| 序号 | int | 数据源序号 |
| 代码 | str | 6 位股票代码 |
| 名称 | str | 中文简称 |
| 最新价 | float | 当前价 |
| 涨跌幅 | float | % |
| 涨跌额 | float | 元 |
| 成交量 | float | 当前累计（手） |
| 成交额 | float | 当前累计（元） |
| 振幅 | float | % |
| 最高 / 最低 | float | 今日 |
| 今开 / 昨收 | float | 今日 |
| 量比 | float | — |
| 换手率 | float | % |
| 市盈率-动态 | float | 动态 PE |
| 市净率 | float | PB |
| 总市值 | float | 元 |
| 流通市值 | float | 元 |
| 涨速 | float | %/min |
| 5分钟涨跌 | float | % |
| 60日涨跌幅 | float | % |
| 年初至今涨跌幅 | float | % |

## 6.2 `data/stock_zh_a_spot_em_filtered.csv`

**来源**：`main.ipynb` 阶段 B
**记录数**：3403 行 × 3 列（`序号 / 代码 / 名称`）

> 板块过滤规则详见 [02 · 数据流水线](./02-data-pipeline.md#阶段-b板块--nan-过滤)。注意 **未剔除 `92` 开头** 的北交所股票。

## 6.3 `data/stock_zh_a_spot_em_filtered_with_suffix.csv`

**来源**：`main.ipynb` 阶段 C
**记录数**：3403 行
**新增列**：`代码_full`（带 `.SZ` / `.SH` / `.BJ` 后缀）

| 原代码 | 加后缀规则 |
| --- | --- |
| 以 `0/2/3` 开头 | `code + ".SZ"` |
| 以 `6` 开头 | `code + ".SH"` |
| 以 `8/9` 开头 | `code + ".BJ"` |
| 其他 | 原样返回 |

## 6.4 `data/stock_daily_data/<code>.csv`

**来源**：`ak.stock_zh_a_hist(symbol, period="daily", adjust="")`（**不复权**）
**记录数**：每个文件约 6000+ 行（2000-01-01 至 2025-12-31）
**总文件数**：3403 个

| 列 | 类型 | 说明 |
| --- | --- | --- |
| 日期 | str | YYYY-MM-DD |
| 股票代码 | str | 6 位 |
| 开盘 | float | 元 |
| 收盘 | float | 元 |
| 最高 | float | 元 |
| 最低 | float | 元 |
| 成交量 | float | 手 |
| 成交额 | float | 元 |
| 振幅 | float | % |
| 涨跌幅 | float | %（不复权口径） |
| 涨跌额 | float | 元 |
| 换手率 | float | % |

> 退市 / 停牌期间字段可能为 NaN。

## 6.5 `data/all_stocks_daily.csv`

**来源**：`main.ipynb` 阶段 E，合并所有 `stock_daily_data/*.csv`
**记录数**：~11,919,521 行
**列**：与单文件相同 + 多了一个冗余的 `代码` 列

## 6.6 `data/A股_日行情_年报_流通市值.csv` ⭐ 核心

**来源**：`main.ipynb` 阶段 F
**记录数**：~3,800,000+ 行（2018-01-01 之后）
**大小**：~800MB

| 列 | 来源 | 说明 |
| --- | --- | --- |
| 日期 | 日线 | pd.Timestamp |
| 代码 | 阶段 C 补 | 6 位字符串 |
| 股票代码 | 日线 | 6 位字符串（与 `代码` 重复） |
| 名称 | 阶段 C 补 | 中文简称 |
| 股票代码_full | 阶段 C 补 | 带后缀 |
| 开盘 / 收盘 / 最高 / 最低 | 日线 | 元 |
| 成交量 / 成交额 | 日线 | 手 / 元 |
| 振幅 / 涨跌幅 / 涨跌额 / 换手率 | 日线 | — |
| EPSJB | 年报 | 基本每股收益（元） |
| ROEJQ | 年报 | 加权净资产收益率（%） |
| NOTICE_DATE | 年报 | 公告日 |
| 流通市值 | stock_value_em | 元 |

> **回测与实时选股唯一数据源**。建议做只读快照，避免被下游误改。

## 6.7 `data/trading_records.csv`

**来源**：`选股.ipynb` 单元 #3
**记录类型**：3 种 `操作` = `买入` / `卖出` / `持仓统计`

| 操作 | 字段 | 说明 |
| --- | --- | --- |
| 买入 | 日期 / 股票代码 / 价格 / 股数 / 金额 / 佣金 / 现金余额 | 买入成交 |
| 卖出 | 日期 / 股票代码 / 价格 / 股数 / 金额 / 印花税 / 佣金 / 现金余额 | 卖出成交 |
| 持仓统计 | 日期 / 现金 / 持仓市值 / 总资产 | 每日快照 |

## 6.8 `data/financial_analysis_indicator_columns.txt`

**来源**：`main.ipynb` 单元 #8，将 `ak.stock_financial_analysis_indicator_em` 的 DataFrame 列名写入
**列数**：140 列（覆盖一般工商业、银行、保险、券商、综合金融）

详见 [02 · 数据流水线 §财务指标列名参考](./02-data-pipeline.md#财务指标列名参考)。

## 6.9 `data/指标.txt`

**来源**：手工注释（前 44 列的中文释义）
**用途**：作为 `financial_analysis_indicator_columns.txt` 的人类可读版本。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| SECUCODE | object | 股票代码（带后缀） |
| SECURITY_CODE | object | 股票代码 |
| EPSJB | float64 | 基本每股收益（元） |
| EPSKCJB | float64 | 扣非每股收益（元） |
| EPSXS | float64 | 稀释每股收益（元） |
| BPS | float64 | 每股净资产（元） |
| MGZBGJ | float64 | 每股公积金（元） |
| TOTALOPERATEREVE | float64 | 营业总收入（元） |
| MLR | float64 | 毛利润（元） |
| PARENTNETPROFIT | float64 | 归属净利润（元） |
| ROEJQ | float64 | 净资产收益率（加权，%） |
| ROEKCJQ | float64 | 净资产收益率（扣非/加权，%） |
| XSJLL | float64 | 净利率（%） |
| XSMLL | float64 | 毛利率（%） |
| ZCFZL | float64 | 资产负债率（%） |
| ... | ... | ... |

## 6.10 `data/trading_records.xlsx` / `trading_records(260103策略).xlsx`

`选股.ipynb` 的不同次运行结果（人工另存为 xlsx）。文件名中的"260103"对应 2026-01-03 策略快照。
