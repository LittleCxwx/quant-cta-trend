# 08 · 新版架构（scripts / web / tests）

> 2026-06 重构说明。原 `code/*.ipynb` 已迁移到 `scripts/`，新增 Web 前端与单元测试。

## 🎯 重构目标

| 目标 | 解决方案 |
| --- | --- |
| 1. 快速增量爬取 | `scripts/data/update_all.py` + 断点续传 + 重试装饰器 |
| 2. Web 可视化 | `web/` 单页 HTML + ECharts + FastAPI 后端 |
| 3. Git 标准化 | `.gitignore` / `.gitattributes` / `LICENSE` / `requirements.txt` |
| 4. AI 友好 | `scripts/strategy/*.py` 全部带 type hints + Google-style docstring + CLI |
| 5. 可测试性 | 34 个 pytest 单元测试覆盖核心逻辑 |

## 📁 完整目录树

```
quant-cta-trend/
├── .gitignore
├── .gitattributes
├── LICENSE
├── README.md
├── requirements.txt
│
├── scripts/                          # ★ 核心代码库
│   ├── __init__.py
│   ├── README.md
│   ├── common.py                     # 路径/重试/板块过滤
│   ├── cli.py                        # 统一 CLI 入口
│   │
│   ├── data/                         # 数据爬取
│   │   ├── __init__.py
│   │   ├── fetch_daily.py            # 增量拉日 K 线
│   │   ├── fetch_market_value.py     # 增量拉流通市值
│   │   ├── fetch_annual.py           # 拉最新年报(可选)
│   │   ├── build_unified.py          # 合并统一底表
│   │   └── update_all.py             # 一键更新
│   │
│   └── strategy/                     # 策略逻辑
│       ├── __init__.py
│       ├── data_loader.py            # DataLoader 类
│       ├── select_stocks.py          # select_stocks / select_stocks_for_date
│       ├── trading_signals.py        # get_signals_for_date
│       └── backtest.py               # run_backtest
│
├── web/                              # ★ Web 前端
│   ├── __init__.py
│   ├── README.md
│   ├── backend.py                    # FastAPI 入口
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
│
├── tests/                            # ★ 单元测试
│   ├── __init__.py
│   ├── test_common.py
│   ├── test_select_stocks.py
│   └── test_trading_signals.py
│
├── docs/                             # 文档
│   ├── README.md
│   ├── 01-project-overview.md
│   ├── 02-data-pipeline.md
│   ├── 03-stock-selection-strategy.md
│   ├── 04-backtest.md
│   ├── 05-future-stock-selection.md
│   ├── 06-data-dictionary.md
│   ├── 07-known-issues.md
│   └── 08-new-architecture.md        # 本文件
│
├── data/                             # 数据(被 .gitignore)
│   ├── .progress/                    # 断点续传
│   ├── annual_cache/                 # 财报缓存(可选)
│   ├── market_value_cache/           # 市值缓存
│   ├── stock_daily_data/             # 3403 个 CSV
│   ├── stock_zh_a_spot_em_filtered.csv
│   ├── stock_zh_a_spot_em_filtered_with_suffix.csv
│   ├── all_stocks_daily.csv
│   └── A股_日行情_年报_流通市值.csv
│
└── code/                             # 原始 Jupyter(legacy,只读)
    ├── main.py
    ├── main.ipynb
    ├── test.ipynb
    ├── 选股.ipynb
    └── 未来选股.ipynb
```

## 🔁 迁移对照表

| 原 `code/*.ipynb` 单元格 | 新位置 |
| --- | --- |
| `main.ipynb` 阶段 A:拉快照 | 不再需要(已在 `data/` 缓存) |
| `main.ipynb` 阶段 B:过滤板块 | `scripts/common.py::EXCLUDED_PREFIXES` + `scripts/strategy/select_stocks.py::_filter_excluded_codes` |
| `main.ipynb` 阶段 C:加后缀 | `scripts/common.py::add_market_suffix` |
| `main.ipynb` 阶段 D:拉日线 | `scripts/data/fetch_daily.py` |
| `main.ipynb` 阶段 E:合并日线 | `scripts/data/build_unified.py::_rebuild_all_daily_csv` |
| `main.ipynb` 阶段 F:合并年报+市值 | `scripts/data/build_unified.py::_process_one_stock` |
| `选股.ipynb` 主回测 | `scripts/strategy/backtest.py::run_backtest` |
| `选股.ipynb` 画图 | `web/static/app.js::renderChart` (ECharts) |
| `选股.ipynb` 评价指标 | `scripts/strategy/backtest.py::_calc_metrics` |
| `未来选股.ipynb` 主函数 | `scripts/strategy/trading_signals.py::generate_signals` |

## 🆕 增量更新（核心改进）

旧版需要重跑全量（13 分钟拉日线 + 47 分钟拉市值）。
新版 **只补 2026-01-01 之后**：

```bash
python -m scripts.cli update --start 2026-01-01
```

**时间估算**：
- 拉日线（2026-01-01 ~ 2026-06-07，约 100 个交易日）：约 1-2 分钟
- 拉市值（全量但本地有缓存则秒过）：< 1 分钟
- 合并统一底表（增量 append）：< 30 秒

**总计**：约 2-3 分钟（取决于网络）。

## 🌐 Web 可视化

- 后端：`web/backend.py`（FastAPI 单文件，约 200 行）
- 前端：`web/static/index.html` + `app.js` + `style.css`（约 400 行总计）
- 图表：ECharts 通过 CDN 加载，无 npm

**功能**：
- 选股 Tab → 表格 + 评价
- 回测 Tab → 资金曲线 + 回撤阴影 + 评价指标卡片 + 交易记录
- 信号 Tab → BUY/SELL/HOLD 分块，含"原因"列
- 数据 Tab → 数据状态 + CLI 更新命令

## 🧠 AI 友好性

`scripts/strategy/*.py` 每个公开函数都遵循：

```python
def func_name(arg1: type, arg2: type = default) -> ReturnType:
    """一句话功能描述。

    Args:
        arg1: 说明。
        arg2: 说明。

    Returns:
        返回类型: 说明。

    Raises:
        异常类型: 触发条件。

    Example:
        >>> result = func_name("2026-06-07")
    """
```

LLM 可以：
1. 直接 `from scripts.strategy import select_stocks_for_date`
2. 读 docstring 知道参数含义
3. 看 `Example` 直接抄用法

## 🧪 测试覆盖

```bash
$ python -m pytest tests/ -v
...
============================== 34 passed in 0.47s ==============================
```

| 测试文件 | 覆盖 |
| --- | --- |
| `test_common.py` | normalize_code / add_market_suffix / is_excluded / parse_date / retry |
| `test_select_stocks.py` | 板块过滤 / 基本面过滤 / 排序 / Top N / 边界 |
| `test_trading_signals.py` | 周三卖出 / 周四买入 / 持有 / 涨停跳过 |

## 🚧 已知遗留

`code/*.ipynb` 没有删除，标记为 **legacy**。
新代码应只依赖 `scripts/`，避免在两边维护同一逻辑。

详见 [07 · 已知问题与改进建议](./07-known-issues.md)。
