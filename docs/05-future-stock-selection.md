# 05 · 实时选股（`code/未来选股.ipynb`）

`未来选股.ipynb` 是 `选股.ipynb` 中 `select_stocks` 函数的"工程化封装"，用于在某个**未来交易日**直接给出 Top N 候选股。

> 作者在 markdown 中写道：
> > 以当前的数据给未来选股。**财务数据需要提前存储**（年报久久获取一次即可），行情 / 市值数据则通过 akshare 实时拉取。

## 核心设计

```
输入: trade_date (str / Timestamp)
       │
       ▼
读取带后缀代码表 (stock_zh_a_spot_em_filtered_with_suffix.csv)
       │
       ▼
遍历每只股票
   ├─ 板块过滤 (30x/301/688/689/8/92/43)
   ├─ 财务过滤 (EPS > 0, ROE > 10)
   ├─ 行情拉取 (load_daily_price)  ← 带重试
   └─ 流通市值拉取 (load_market_value)  ← 带重试
       │
       ▼
按 流通市值 升序排序
       │
       ▼
保存 stock_list_{YYYYMMDD}.csv
       │
       ▼
返回前 select_stock_num = 5 只
```

## 辅助函数

```python
def load_latest_financial_single(stock_code: str, trade_date: pd.Timestamp):
    """
    从预存的 nianbao_df 中按 trade_date 前最近的年报取 EPSJB / ROEJQ
    """
    nianbao_df = pd.read_csv("../data/A股_日行情_年报_流通市值.csv",
                             dtype={"股票代码": str})
    nianbao_df["日期"] = pd.to_datetime(nianbao_df["日期"])
    
    sub = nianbao_df[
        (nianbao_df["股票代码_full"] == stock_code) &
        (nianbao_df["日期"] <= trade_date)
    ]
    if sub.empty:
        return None
    # 取 NOTICE_DATE 最大的那一行（即最新一期年报）
    sub = sub.sort_values("NOTICE_DATE", ascending=False).iloc[0]
    return {
        "NOTICE_DATE": sub["NOTICE_DATE"],
        "EPSJB":       sub["EPSJB"],
        "ROEJQ":       sub["ROEJQ"],
    }


def load_daily_price(symbol: str, trade_date: pd.Timestamp):
    """
    拉 5 分钟 K 线，返回最后一行（不复权）
    """
    df = ak.stock_zh_a_hist_min_em(
        symbol=symbol,
        start_date="2000-01-01 09:30:00",
        period="5",
        adjust=""
    )
    # 取 trade_date 当日最后一行
    ...


def load_market_value(symbol: str, trade_date: pd.Timestamp):
    """
    拉历史流通市值，过滤到 trade_date 之前，取最近一个交易日
    """
    df = ak.stock_value_em(symbol=symbol)
    df["数据日期"] = pd.to_datetime(df["数据日期"])
    df = df[df["数据日期"] <= trade_date]
    if df.empty:
        return None
    return df.sort_values("数据日期").iloc[-1]["流通市值"]


def fetch_with_retry(fetch_func, max_retry=5, sleep_sec=1, desc=""):
    """
    通用重试封装：最多 5 次，每次间隔 1 秒
    """
    for i in range(max_retry):
        try:
            return fetch_func()
        except Exception as e:
            print(f"[{desc}] 第 {i+1} 次失败: {e}")
            time.sleep(sleep_sec)
    return None
```

## 主函数

```python
def select_stocks_on_date(trade_date, stock_list_csv, select_stock_num=5):
    trade_date = pd.Timestamp(trade_date)
    stock_list = pd.read_csv(stock_list_csv, dtype={"代码": str})

    results = []
    for _, row in tqdm(stock_list.iterrows(), total=len(stock_list)):
        code      = row["代码"]
        code_full = row["代码_full"]
        name      = row["名称"]

        # 板块过滤
        if code.startswith(('300', '301', '688', '689', '8', '92', '43')):
            continue

        # 财务数据
        fin = load_latest_financial_single(code_full, trade_date)
        if fin is None:
            continue
        if not (fin["EPSJB"] > 0 and fin["ROEJQ"] > 10):
            continue

        # （注释掉）实时行情 / 流通市值
        # price = fetch_with_retry(lambda: load_daily_price(code, trade_date), desc=f"价格-{code}")
        # mv    = fetch_with_retry(lambda: load_market_value(code, trade_date), desc=f"市值-{code}")

        results.append({
            "代码":       code,
            "名称":       name,
            "EPS":        fin["EPSJB"],
            "ROE":        fin["ROEJQ"],
            # "收盘价":    price,
            # "流通市值":  mv,
        })

    df = pd.DataFrame(results)
    df = df.sort_values("流通市值")  # ⚠️ 字段未填充，会 KeyError 或全 NaN
    df.to_csv(f"../data/stock_list_{trade_date.strftime('%Y%m%d')}.csv", index=False)
    return df.head(select_stock_num)
```

## 调用方式

```python
selected_df = select_stocks_on_date(trade_date="2025-12-25", select_stock_num=5)
print("2025-12-25 选股结果:", selected_df)
```

> 笔记本底部还预留了"今日 09:30 选股"的模板（被注释），可改造为定时任务。

## 已知缺陷

1. **行情 / 市值实时拉取被注释**：循环中 `price`、`mv` 没有真正赋值，但 `df.sort_values("流通市值")` 仍引用该列，运行时会 `KeyError` 或全 NaN 排序。
2. **没有最小流动性 / 价格阈值**：可能选到接近退市的仙股。
3. **未校验 `load_daily_price` 当日是否交易**：5 分钟 K 线可能跨日，需要按日期切片。
4. **重试间隔固定 1 秒**：东财高频封 IP 时应改为指数退避。
5. **未做缓存**：每次运行都对 3400 只股票全量调用 akshare，建议加 `lru_cache` 或落盘。

详见 [07-已知问题与改进建议](./07-known-issues.md)。
