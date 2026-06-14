# 03 · 选股策略

> 选股逻辑在 `选股.ipynb` 和 `未来选股.ipynb` 中**完全一致**，是项目核心。

## 函数签名

```python
def select_stocks(day_df: pd.DataFrame, select_stock_num: int = 5) -> pd.DataFrame:
    """
    周四低价+基本面+小市值策略
    """
    ...
```

参数 `day_df` 是一个**单日**的全市场快照（包含至少字段：`股票代码 / 收盘 / EPSJB / ROEJQ / 流通市值`）。

## 过滤 / 排序流程

```
输入: 某一日全市场数据 (groupby 后的 day_df)
       │
       ▼
[1] 板块过滤：剔除 30x / 301 / 688 / 689 / 8 / 92 / 43 开头
       │
       ▼
[2] 基本面过滤：EPSJB > 0 且 ROEJQ > 10
       │
       ▼
[3] （注释）低价过滤：收盘价最低 10% 分位以下
       │
       ▼
[4] 小市值排序：按 流通市值 升序
       │
       ▼
[5] 取前 select_stock_num = 5 只
       │
       ▼
输出: pd.DataFrame [股票代码, 名称, EPSJB, ROEJQ, 收盘, 流通市值]
```

## 详细规则

### 1. 板块过滤

```python
def _is_excluded(code: str) -> bool:
    return code.startswith(('300', '301', '688', '689', '8', '92', '43'))
```

| 前缀 | 板块 | 剔除 |
| --- | --- | --- |
| `300` / `301` | 创业板 | ✅ |
| `688` / `689` | 科创板 | ✅ |
| `8` | 北交所（`83xxxx` / `87xxxx`） | ✅ |
| `92` | 北交所（`92xxxx`） | ✅ |
| `43` | 北交所（`43xxxx`，新三板精选层历史遗留） | ✅ |
| `000` / `002` | 深市主板 | ❌ |
| `600` / `601` / `603` / `605` | 沪市主板 | ❌ |

> 比 `main.ipynb` 阶段 B 更严格，**涵盖了 `92` 开头**，可弥补 main 阶段的遗漏。

### 2. 基本面过滤

```python
df = df[(df['EPSJB'] > 0) & (df['ROEJQ'] > 10)]
```

- `EPSJB`（基本每股收益）> 0：保证盈利。
- `ROEJQ`（加权 ROE）> 10%：保证股东回报水平。

> `未来选股.ipynb` 中 ROE 阈值硬编码 `10`，未来调参时建议统一提到配置字典。

### 3. （已注释）低价过滤

```python
# price_threshold = df['收盘'].quantile(0.1)
# df = df[df['收盘'] <= price_threshold]
```

设计者原本希望叠加"低价股"作为辅助因子，但代码注释掉了，目前策略纯靠小市值驱动。

### 4. 小市值排序

```python
df = df.sort_values('流通市值', ascending=True)
return df.head(select_stock_num)
```

`select_stock_num` 默认 5，回测中固定 5。

## 实际选股流程（在 `选股.ipynb` 中）

```python
grouped = full_df.groupby('日期')
for trade_date, day_df in grouped:
    # ... 撮合逻辑 ...
    if trade_date.weekday() == 3:  # 周四
        selected_df = select_stocks(prev_day_df, select_stock_num=5)  # 用前一天数据
        # 等权买入
```

**关键细节**：

- 选股信号日 = **周三**（用 `prev_day_df`）；实际下单日 = **周四开盘**（按周三收盘价撮合）。
- 这是一种 T+1 简化：避免使用"未来数据"，但**未考虑周四开盘跳空**。
- 持仓数量受限于 `cash`：`cash_per_stock = cash / len(selected_df)`，现金不足则**整只跳过**（不部分买入）。

## 选股输出列

```python
results.append({
    "代码": code,
    "名称": name,
    "EPS": eps,
    "ROE": roe,
    "收盘价": price,   # 未来选股中可能为 None
    "流通市值": mv,    # 未来选股中可能为 None
})
```

## 参数与可调项

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `select_stock_num` | 5 | 选股数量 |
| EPS 阈值 | 0 | 基本每股收益 > 0 |
| ROE 阈值 | 10 | 净资产收益率（%） |
| 排序键 | 流通市值升序 | 小市值 |
| 过滤板块 | 30x/301/688/689/8/92/43 | 主板以外全剔 |

> **可改进**：可将过滤条件、阈值改为配置字典（如 `config.yaml`）或函数参数，方便做参数敏感性测试。
