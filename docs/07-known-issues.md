# 07 · 已知问题与改进建议

本文汇总目前实现的**实际缺陷**和**可改进方向**，按优先级排列。

## 🔴 P0：会导致错误或数据不一致

### 1. `未来选股.ipynb` 中 `sort_values("流通市值")` 字段缺失

```python
results.append({...})        # 循环里没有写入 "流通市值"
...
df = df.sort_values("流通市值")  # KeyError
```

行情 / 市值的拉取代码被整体注释掉，导致 `流通市值` 列在 `results` 中始终不存在。直接运行会 `KeyError: '流通市值'`。
**修复**：

```python
results.append({
    ...
    "流通市值": mv,   # 把被注释的 fetch_with_retry(..., "市值-...") 恢复
})
```

或临时改用本地 `A股_日行情_年报_流通市值.csv` 中的 `流通市值`。

### 2. 阶段 B 未剔除 `92` 开头北交所股票

```python
stock_zh_a_spot_em_df[~stock_zh_a_spot_em_df['代码'].str.startswith(('30','68','83','43','87'))]
# 缺 '92'
```

导致 `stock_zh_a_spot_em_filtered.csv` 混入北交所 `92xxxx` 股票。
**修复**：在 main 与 select_stocks 中统一使用同一过滤集合 `'300','301','688','689','8','92','43'`。

### 3. ST / *ST 过滤被注释

`select_stocks` 不过滤 ST，导致：
- ST 股 5% 涨跌停与策略的 10% 判定不一致。
- 风险股进入持仓。

**修复**：

```python
df = df[~df['名称'].str.contains(r'ST|\*ST')]
```

### 4. `all_stocks_daily.csv` 缺代码列重复

合并时 `df.insert(0, '代码', code)` 后，`股票代码` 列仍存在 → 字段冗余，存储浪费 30%。

**修复**：合并时直接 rename `股票代码` → `代码`。

## 🟠 P1：可能导致回测结果偏离实际

### 5. 涨跌停一字板买入失败未处理

周四开盘时如果目标股涨停一字板，按策略仍然按"收盘价 × 100 股"成功买入；实际无法成交。

**修复**：在周四买入循环中检查当日 `is_limit_up`，跳过一字板。

### 6. 停牌股票未处理

周三卖出时如果停牌，`day_df[day_df['股票代码'] == code]` 返回空表 → 跳过卖出，仓位实际仍持有。
但程序记录中"已删除 positions[code]"的逻辑缺失，**下一日仍会尝试卖出**。

**修复**：保留 `positions[code]` 在停牌期间，并在下一个非停牌日补卖。

### 7. 现金不足时不平摊

```python
cash_per_stock = cash / len(selected_df)
if cash < cost + commission: continue
```

当现金恰好不够买 1 手时，**整只跳过**，实际仓位不满 5 只。
**修复**：

```python
# 按 cash 实际可用额按比例分配
remaining_cash = cash
for i, (_, s) in enumerate(selected_df.iterrows()):
    if i == len(selected_df) - 1:
        cash_for_this = remaining_cash
    else:
        cash_for_this = cash * (len(selected_df) - i - 1) / (len(selected_df) - i)
    ...
```

或更简单：循环内"重算 cash_per_stock"。

### 8. 不复权数据用于长期回测

日线 `adjust=""` 不复权，**未做分红送股处理**。当一只股票发生 10 送 10，价格"腰斩"但实际收益不变，策略会误判跌停。

**修复**：在合并日线时改用 `adjust="hfq"`（后复权），并在文档中说明价格口径。

### 9. 印花税用 1‰

2023 年 8 月起 A 股印花税已降至 0.5‰（卖出单边）。

**修复**：

```python
t_rate = 0.5 / 1000
```

## 🟡 P2：工程化与可维护性

### 10. `select_stocks` 在两处重复实现

`选股.ipynb` 和 `未来选股.ipynb` 各自内联了选股逻辑，**逻辑漂移风险大**。

**修复**：抽到 `code/select_stocks.py`，两处 `from select_stocks import select_stocks`。

### 11. 无配置文件

阈值（EPS、ROE、select_stock_num、手续费）全部硬编码在 notebook cell 中。

**修复**：新增 `config.yaml`：

```yaml
strategy:
  select_stock_num: 5
  eps_threshold: 0
  roe_threshold: 10
  exclude_prefix: ["300","301","688","689","8","92","43"]
  exclude_st: true
trading:
  c_rate: 0.00012
  t_rate: 0.0005
  init_cash: 10000
```

### 12. 无断点续传 / 缓存

阶段 D（3403 只日线下载）和阶段 F（3403 只年报 / 市值）都没有持久化进度。

**修复**：
- 阶段 D：写 `data/.downloaded.txt` 记录已下载代码。
- 阶段 F：用 `functools.lru_cache` 或落盘 `data/financial/<code>.parquet` 缓存。

### 13. matplotlib 中文字体硬编码

```python
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', ...]
```

在 Linux / Docker 环境下 `SimHei` 不存在，会显示方框。

**修复**：在 `matplotlib` 启动时探测可用字体，或在文档中提示安装 `wqy-microhei` / `noto-cjk`。

### 14. 财务数据 merge_asof 容差未设

```python
pd.merge_asof(df, annual_df, left_on='日期', right_on='NOTICE_DATE', direction='backward')
```

年报发布与下一个交易日间隔可能跨周末 / 节假日，`direction='backward'` 行为是"取最近一次发布"，但容差默认是任意大。如果某日**早于**最新一次年报，会拿到空值。

**修复**：

```python
pd.merge_asof(df, annual_df, left_on='日期', right_on='NOTICE_DATE',
              direction='backward', allow_exact_matches=True, tolerance=pd.Timedelta('365 days'))
```

### 15. 没有单元测试

建议补 `code/tests/`：

```python
def test_select_stocks_excludes_kechuang():
    day_df = pd.DataFrame({
        "股票代码": ["300750", "600519", "688981"],
        "EPSJB":   [10, 30, 5],
        "ROEJQ":   [20, 25, 15],
        "流通市值": [1e9, 2e10, 3e9],
        "收盘":    [100, 2000, 300],
    })
    out = select_stocks(day_df, select_stock_num=5)
    assert "300750" not in out['股票代码'].values
    assert "688981" not in out['股票代码'].values
```

## 🟢 P3：策略增强方向

### 16. 增加换手率 / 量比 / 行业过滤

小市值的"仙股"风险高，建议叠加：
- 换手率 > 1%（保证流动性）
- 排除 PE 负值且连续亏损
- 排除申万行业"房地产 / 钢铁 / 煤炭"等周期股

### 17. 优化持仓周期

当前固定 6 个交易日（周四 → 周三）。可改为：
- 5 日均线 / 10 日均线跌破则止盈止损
- 月底再平衡

### 18. 多因子打分

把"小市值 + EPS + ROE"改为打分制：
```python
score = 0.5 * rank(流通市值, ascending=True) \
      + 0.3 * rank(EPSJB) \
      + 0.2 * rank(ROEJQ)
```
然后选 Top 5，并做相关性分析。

### 19. 行业中性化

小市值策略常在某些行业（如小盘成长）暴露过高，可对申万一级行业做行业中性化（每个行业内选固定 N 只）。

### 20. 多策略组合

可加入：
- 沪深 300 等权 ETF（基准对冲）
- 可转债打新
- 北交所 30 强

## 📋 改进路线图（建议）

| 阶段 | 目标 | 主要工作 |
| --- | --- | --- |
| 1. 修 bug | 消除运行时错误 | #1, #2, #3, #4 |
| 2. 提质量 | 让回测更贴近真实 | #5, #6, #7, #8, #9 |
| 3. 重构 | 抽模块 + 配置文件 | #10, #11, #12 |
| 4. 增强 | 多因子 / 行业中性 / 测试 | #15, #16, #17, #18, #19 |
| 5. 上线 | 实时数据 + 模拟盘 | 把 `未来选股.ipynb` 包装成定时任务 + 飞书/钉钉通知 |
