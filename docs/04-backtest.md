# 04 · 历史回测（`code/选股.ipynb`）

`选股.ipynb` 是项目的**核心策略实现**，完整模拟了"周四选股买入 → 下周三卖出"的周频轮动策略，并输出评价指标 + 资金曲线图。

## 0. 依赖与参数

```python
import pandas as pd, numpy as np, matplotlib.pyplot as plt, akshare as ak

# 参数
start_date        = pd.to_datetime("2018-01-01")
select_stock_num  = 5
c_rate            = 1.2 / 10000   # 手续费（双边）
t_rate            = 1.0 / 1000    # 印花税（卖出单边）
init_cash         = 10000
```

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `start_date` | 2018-01-01 | 回测起点 |
| `select_stock_num` | 5 | 每期持仓数 |
| `c_rate` | 1.2‱ | 券商佣金（约万 1.2，双边） |
| `t_rate` | 1‰ | 印花税（卖出单边） |
| `init_cash` | 10,000 元 | 初始资金 |

> 实际 2023 年起印花税已降至 0.5‰，A 股目前是 0.5‰ 单边。回测中用 1‰ 偏保守，可作为安全垫。

## 1. 全局状态

```python
cash       = init_cash
positions  = {}            # {股票代码: 股数}
records    = []            # 事件流：买入/卖出/持仓统计
position_records = []      # 每日持仓快照
prev_day_df = None         # 上一交易日数据（用于周四选股）
```

## 2. 涨跌停标记

每个交易日 group 内对每只股票计算：

```python
group['prev_close'] = group.groupby('股票代码')['收盘'].shift(1)
eps = 1e-6
group['is_limit_up']   = group['收盘'] >= group['prev_close'] * 1.10 - eps
group['is_limit_down'] = group['收盘'] <= group['prev_close'] * 0.90 + eps
```

- A 股主板 10% 涨跌停阈值。
- `eps=1e-6` 是浮点容差。
- ⚠️ **ST 股 5% 阈值未特殊处理**，但 `select_stocks` 不剔 ST，因此可能误判。

## 3. 撮合主循环

```python
for trade_date, day_df in grouped:
    # ... 涨跌停标记 ...
    
    if trade_date.weekday() == 2:        # 周三：卖出
        for code, shares in positions.items():
            row = day_df[day_df['股票代码'] == code]
            if row.empty: continue
            if row['is_limit_up'].iloc[0]: continue   # 涨停不能卖
            price = row['收盘'].iloc[0]
            sell_amount = price * shares
            tax = sell_amount * t_rate
            commission = sell_amount * c_rate
            cash += sell_amount - tax - commission
            records.append({...操作="卖出"...})
            del positions[code]
    
    elif trade_date.weekday() == 3:      # 周四：买入
        selected = select_stocks(prev_day_df, select_stock_num)
        cash_per_stock = cash / len(selected)
        for _, s in selected.iterrows():
            price = s['收盘']
            shares = int(cash_per_stock // (price * 100)) * 100  # 100 股取整
            if shares == 0: continue
            cost = price * shares
            commission = cost * c_rate
            if cash < cost + commission: continue
            cash -= cost + commission
            positions[s['股票代码']] = positions.get(s['股票代码'], 0) + shares
            records.append({...操作="买入"...})
    
    # 每日快照
    for code, shares in positions.items():
        position_records.append({"日期": trade_date, "股票代码": code, "持股数": shares})
    
    market_value = sum(
        day_df[day_df['股票代码'] == c]['收盘'].iloc[0] * s
        for c, s in positions.items() if not day_df[day_df['股票代码'] == c].empty
    )
    total_asset = cash + market_value
    records.append({"日期": trade_date, "操作": "持仓统计",
                    "现金": cash, "持仓市值": market_value, "总资产": total_asset})
    
    prev_day_df = day_df
```

### 撮合规则详解

| 场景 | 行为 |
| --- | --- |
| 周三涨停 | **不卖**（一字板卖不出），继续持仓 |
| 周三非涨停 | 按收盘价全仓卖出，扣印花税 + 佣金 |
| 周四买入 | 按**周三收盘价**等权买入（不考虑周四开盘跳空） |
| 买入取整 | 100 股一手，不足 1 手跳过 |
| 现金不足 | 跳过该股（**不平摊给其他股**） |
| 持仓 1 周 | 周四 → 下周三，约 6 个交易日 |
| 卖出税费 | 印花税 1‰ + 佣金 1.2‱（双边） |
| 买入税费 | 仅佣金 1.2‱ |

## 4. 结果整理

```python
result_df = pd.DataFrame(records)
asset_df = result_df[result_df['操作'] == '持仓统计'][['日期', '现金', '持仓市值', '总资产']]
```

## 5. 基准对比

```python
# 沪深 300
bench = ak.stock_zh_index_daily(symbol="sh000300")
bench = bench[bench['date'] >= start_date].set_index('date')['close']

# 前向填充到 asset_df 的每个交易日
bench = bench.reindex(asset_df['日期']).ffill()

base_index = bench.iloc[0]
asset_df['大盘资金'] = init_cash * bench / base_index
```

> 默认采用"全仓买入并持有沪深 300"的等效资金曲线作为基准。

## 6. 评价指标

```python
asset_df['策略日收益率'] = asset_df['总资产'].pct_change()
asset_df['大盘日收益率'] = asset_df['大盘资金'].pct_change()

asset_df['累计最大值'] = asset_df['总资产'].cummax()
asset_df['策略回撤']   = asset_df['总资产'] / asset_df['累计最大值'] - 1

trading_days = 252
累计收益率 = asset_df['总资产'].iloc[-1] / init_cash - 1
年化收益率 = (1 + 累计收益率) ** (trading_days / len(asset_df)) - 1
最大回撤   = asset_df['策略回撤'].min()
夏普比率   = (asset_df['策略日收益率'].mean() / 
              asset_df['策略日收益率'].std()) * np.sqrt(trading_days)
```

| 指标 | 公式 |
| --- | --- |
| 累计收益率 | `期末总资产 / 初始资金 - 1` |
| 年化收益率 | `(1 + 累计)^(252/交易日数) - 1` |
| 最大回撤 | `min(总资产 / 累计最大值 - 1)` |
| 夏普比率 | `mean(日收益) / std(日收益) * sqrt(252)`，无风险利率 = 0 |

## 7. 画图

```python
fig, ax1 = plt.subplots(figsize=(14, 7))

# 左轴：资金
ax1.plot(资产日期, 总资产,  label='策略总资产', color='tab:blue')
ax1.plot(资产日期, 大盘资金, label='沪深300(基准)', color='tab:orange')
ax1.fill_between(资产日期, 0, 累计最大值, where=策略回撤 < 0,
                 color='red', alpha=0.15, label='策略回撤区间')

# 右轴：收益率
ax2 = ax1.twinx()
ax2.plot(资产日期, 策略累计收益, '--', color='tab:blue', label='策略累计收益(右轴)')
ax2.plot(资产日期, 大盘累计收益, '--', color='tab:orange', label='大盘累计收益(右轴)')
ax2.plot(资产日期, 策略回撤, ':', color='red', label='策略回撤(右轴)')

ax1.set_ylabel('资金 (元)')
ax2.set_ylabel('收益率 / 回撤 (%)')
plt.title('策略资金 & 收益率 vs 大盘基准')
```

- **中文字体**：`plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', ...]`
- `axes.unicode_minus = False`（避免负号变方框）

## 8. 交易记录持久化

```python
records_df = pd.DataFrame(records)
records_df.to_csv("../data/trading_records.csv", index=False)
```

输出字段：`日期 / 操作 / 股票代码 / 价格 / 股数 / 金额 / 税费 / 现金 / 总资产`。

## 9. 辅助图：上证指数走势

`选股.ipynb` 末尾另画一张"A 股大盘走势（上证指数）"，方便对照策略与大势。

## 已知偏差

1. **未模拟停牌**：若周三停牌，程序取到的是 `NaN`，可能导致卖出循环出错。
2. **未考虑涨跌停一字板买入失败**：周四可能因涨停买不进，策略未做撤单/改单。
3. **未考虑滑点**：所有成交价都用收盘价近似。
4. **ST 5% 阈值**：用 10% 判定会过严，可能误判跌停。
5. **现金不足时不平摊**：可能导致部分股票没买到，仓位不满。
6. **未做分红送股处理**：用的是不复权数据，长期持仓可能有偏差。

详见 [07-已知问题与改进建议](./07-known-issues.md)。
