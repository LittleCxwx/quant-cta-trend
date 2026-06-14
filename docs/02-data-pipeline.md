# 02 · 数据流水线（`code/main.ipynb`）

`main.ipynb` 是整个项目的数据底座。它按 6 个阶段生成策略所需的统一底表 `A股_日行情_年报_流通市值.csv`。

## 阶段 A：拉取 A 股全量快照

```python
import akshare as ak
stock_zh_a_spot_em_df = ak.stock_zh_a_spot_em()
```

- 数据源：东方财富沪深京 A 股实时行情接口。
- 输出：`data/stock_zh_a_spot_em.csv`（**5790 行 × 23 列**）。
- 包含字段：`序号 / 代码 / 名称 / 最新价 / 涨跌幅 / 涨跌额 / 成交量 / 成交额 / 振幅 / 最高 / 最低 / 今开 / 昨收 / 量比 / 换手率 / 市盈率-动态 / 市净率 / 总市值 / 流通市值 / 涨速 / 5分钟涨跌 / 60日涨跌幅 / 年初至今涨跌幅`。
- **注意点**：作者在 markdown 中强调"该代码连接不稳定，运行成功后只运行一次即可"，建议将 `stock_zh_a_spot_em.csv` 视为不可变的初始快照。

## 阶段 B：板块 / NaN 过滤

目标：保留主板股票，剔除创业板、科创板、北交所、退市股等。

### 步骤 1：剔除缺失最新价的行
```python
stock_zh_a_spot_em_df = stock_zh_a_spot_em_df[stock_zh_a_spot_em_df['最新价'].notna()]
```
去掉 341 行纯 NaN 的退市 / 停牌股（5790 → 5449 行）。

### 步骤 2：按代码前缀剔除高风险板块
```python
stock_zh_a_spot_em_df = stock_zh_a_spot_em_df[
    ~stock_zh_a_spot_em_df['代码'].astype(str).str.startswith(('30', '68', '83', '43', '87'))
]
```

| 前缀 | 板块 | 是否剔除 |
| --- | --- | --- |
| `30x` / `301` | 创业板 | ✅ |
| `688` / `689` | 科创板 | ✅ |
| `83` / `43` / `87` | 北交所 | ✅ |
| `000` / `002` | 深市主板 / 中小板 | ❌ 保留 |
| `600` / `601` / `603` / `605` | 沪市主板 | ❌ 保留 |
| `920` | 北交所（部分） | ❌（未在前缀列表） |

> ⚠️ **遗留缺陷**：北交所代码中 `92` 开头（如 `920xxx`）未被剔除，会混入股票池。回测代码 `选股.ipynb` 中有更严格的二次过滤（详见 03）。

### 步骤 3：ST 过滤（被注释）
```python
# stock_zh_a_spot_em_df = stock_zh_a_spot_em_df[~stock_zh_a_spot_em_df['名称'].str.contains('ST|\*ST')]
```
**ST / *ST 过滤被作者注释掉**，意味着 ST 股进入了股票池。回测中如果策略误买 ST，会因 5% 涨跌停阈值与策略的 10% 判定不一致导致误判。

### 步骤 4：格式归一化
```python
stock_zh_a_spot_em_df = stock_zh_a_spot_em_df.reset_index(drop=True)
stock_zh_a_spot_em_df['序号'] = stock_zh_a_spot_em_df.index + 1
stock_zh_a_spot_em_df['代码'] = stock_zh_a_spot_em_df['代码'].astype(str).str.zfill(6)
stock_zh_a_spot_em_df[['序号', '代码', '名称']].to_csv(
    "../data/stock_zh_a_spot_em_filtered.csv", index=False
)
```

- 输出：`data/stock_zh_a_spot_em_filtered.csv`（**3403 行**）。
- 字段：`序号 / 代码 / 名称`（仅保留 3 列，下游消费）。

## 阶段 C：给代码加市场后缀

```python
def add_suffix(code: str) -> str:
    if code.startswith(("0", "2", "3")):
        return code + ".SZ"
    elif code.startswith("6"):
        return code + ".SH"
    elif code.startswith(("8", "9")):
        return code + ".BJ"
    return code

stock_list["代码_full"] = stock_list["代码"].str.zfill(6).apply(add_suffix)
stock_list.to_csv("../data/stock_zh_a_spot_em_filtered_with_suffix.csv", index=False)
```

- 输出：`stock_zh_a_spot_em_filtered_with_suffix.csv`（3403 行）。
- 用于 `ak.stock_financial_analysis_indicator_em`（要求带后缀的完整代码）。

## 阶段 D：逐只下载日 K 线

```python
import akshare as ak
import pandas as pd
from tqdm import tqdm

code_df = pd.read_csv(r"..\data\stock_zh_a_spot_em_filtered.csv", dtype={"代码": str})

for code in tqdm(code_df["代码"], desc="下载日线"):
    df = ak.stock_zh_a_hist(symbol=code,
                            period="daily",
                            start_date="20000101",
                            end_date="20251231",
                            adjust="")
    df.to_csv(f"../data/stock_daily_data/{code}.csv", index=False, encoding="utf-8-sig")
```

- 数据源：东方财富历史日线接口（不复权）。
- 输出：`data/stock_daily_data/<代码>.csv`（**3403 个文件**）。
- 字段：`日期 / 股票代码 / 开盘 / 收盘 / 最高 / 最低 / 成交量 / 成交额 / 振幅 / 涨跌幅 / 涨跌额 / 换手率`。
- 实际耗时：约 13 分钟（`4.18 it/s`）。
- ⚠️ **风险**：
  - 无断点续传：网络中断需从头再来。
  - 退市股可能在中间报错后整个循环失败，建议加 `try/except`。
  - 接口限流后可能被临时封 IP。

## 阶段 E：合并日线为单文件

```python
from pathlib import Path

folder = Path(r"../data/stock_daily_data")
out_file = "../data/all_stocks_daily.csv"

chunks = []
for fp in folder.glob("*.csv"):
    code = fp.stem
    df = pd.read_csv(fp, dtype={'股票代码': str})
    df.insert(0, '代码', code)
    chunks.append(df)

big = pd.concat(chunks, ignore_index=True)
big['日期'] = pd.to_datetime(big['日期'])
big = big.sort_values(['日期', '股票代码']).reset_index(drop=True)
big.to_csv(out_file, index=False, encoding='utf-8-sig')
```

- 输出：`data/all_stocks_daily.csv`（**~11,919,521 行**）。
- 增加了冗余的 `代码` 列（与 `股票代码` 内容相同，建议后续清理）。

## 阶段 F：合并年报 + 流通市值 → 统一底表

这是**最复杂**的一步，对 3403 只股票逐一拉年报和市值，再做 `merge_asof` 向后回填。

```python
def load_annual_report(symbol_full: str):
    df = ak.stock_financial_analysis_indicator_em(symbol=symbol_full, indicator="按报告期")
    df = df[df["REPORT_TYPE"] == "年报"].copy()
    df["NOTICE_DATE"] = pd.to_datetime(df["NOTICE_DATE"])
    df = df.sort_values("NOTICE_DATE")
    keep_cols = ["NOTICE_DATE", "EPSJB", "ROEJQ"]
    return df[keep_cols]

def load_market_value(symbol: str):
    df = ak.stock_value_em(symbol=symbol)
    df = df.rename(columns={"数据日期": "日期"})
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")
    return df[["日期", "流通市值"]]

def process_single_stock(daily_df, code, code_full, name):
    df = daily_df[daily_df["股票代码"] == code].copy()
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")

    # 年报: 用 merge_asof 向后回填
    try:
        annual_df = load_annual_report(code_full)
        df = pd.merge_asof(df, annual_df,
                           left_on="日期", right_on="NOTICE_DATE",
                           direction="backward")
    except Exception as e:
        print(f"[年报失败] {code} {e}")

    # 流通市值: 用 merge_asof 向后回填
    try:
        mv_df = load_market_value(code)
        df = pd.merge_asof(df, mv_df, on="日期", direction="backward")
    except Exception as e:
        print(f"[市值失败] {code} {e}")

    df["名称"] = name
    df["股票代码_full"] = code_full
    return df

daily_df = pd.read_csv("../data/all_stocks_daily.csv", dtype={"股票代码": str})
daily_df["日期"] = pd.to_datetime(daily_df["日期"])
daily_df = daily_df[daily_df["日期"] >= "2018-01-01"].copy()

result_list = []
for _, row in tqdm(stock_list.iterrows(), total=len(stock_list)):
    df_one = process_single_stock(daily_df, row["代码"], row["代码_full"], row["名称"])
    if df_one is not None:
        result_list.append(df_one)

final_df = pd.concat(result_list, ignore_index=True)
final_df.to_csv("../data/A股_日行情_年报_流通市值.csv", index=False, encoding="utf-8")
```

### 关键设计

- **年报回填**：`merge_asof(direction="backward")` 意味着任一交易日，取**最近一次已发布的年报**作为该日可见的 EPS / ROE。`NOTICE_DATE` 通常是 4 月底前发布上年报，所以 1~4 月期间可看到的是上上年报。
- **流通市值回填**：`ak.stock_value_em` 只能拉到**当前日期之前**的数据，所以"未来值"无法获取——文档生成时间在 2025-12-31 之后，市值数据可回溯至 2018-01-02。
- **执行时间**：约 47 分钟（`1.19 it/s`），瓶颈在 `stock_value_em` 拉历史市值的网络往返。
- **输出**：`A股_日行情_年报_流通市值.csv`（约 800MB），是下游 `选股.ipynb` / `未来选股.ipynb` 共用的**唯一数据源**。

### 字段说明

| 列 | 来源 | 含义 |
| --- | --- | --- |
| `日期` | 日线 | 交易日 |
| `代码` / `股票代码` | 日线 | 6 位代码（两列重复） |
| `名称` | 阶段 C 补 | 中文简称 |
| `股票代码_full` | 阶段 C 补 | 带后缀的代码 |
| `开盘 / 收盘 / 最高 / 最低 / 成交量 / 成交额` | 日线 | 不复权 |
| `振幅 / 涨跌幅 / 涨跌额 / 换手率` | 日线 | 当日 |
| `EPSJB` | 年报 | 基本每股收益（元） |
| `ROEJQ` | 年报 | 净资产收益率（加权，%） |
| `NOTICE_DATE` | 年报 | 公告日 |
| `流通市值` | stock_value_em | 当日流通市值（元） |

## 财务指标列名参考

`data/financial_analysis_indicator_columns.txt` 记录了 `stock_financial_analysis_indicator_em` 的全部 140 列，主要类别：

- 基础信息：`SECUCODE / SECURITY_CODE / SECURITY_NAME_ABBR / REPORT_DATE / REPORT_TYPE`
- 每股指标：`EPSJB / EPSKCJB / EPSXS / BPS / MGZBGJ / MGWFPLR / MGJYXJJE`
- 盈利能力：`TOTALOPERATEREVE / MLR / PARENTNETPROFIT / KCFJCXSYJLR`
- 增长率：`TOTALOPERATEREVETZ / PARENTNETPROFITTZ / KCFJCXSYJLRTZ`
- 收益率：`ROEJQ / ROEKCJQ / ZZCJLL / XSJLL / XSMLL`
- 偿债能力：`LD / SD / XJLLB / ZCFZL / QYCS / CQBL`
- 运营能力：`ZZCZZTS / CHZZTS / YSZKZZTS / TOAZZL / CHZZL / YSZKZZL`
- 行业专用：银行（`TOTALDEPOSITS / GROSSLOANS / NONPERLOAN`）、保险（`EARNED_PREMIUM / SOLVENCY_AR`）、券商（`YYFXZB / JJYWFXZB`）等

`data/指标.txt` 是核心指标的中文注释（截取前 44 个）。
