# 量化 CTA 趋势策略 · A 股小市值轮动

> 周频小市值 + 基本面趋势策略，端到端流水线：**数据增量更新 → 策略回测 → 实时选股 → 交易信号 → Web 可视化**。

## ✨ 核心功能

- **增量数据更新**：基于 AKShare（东方财富接口），只补最近缺失的日线和流通市值，支持断点续传和重试。
- **策略回测**：周四选股买入、下周三卖出（涨停除外），含手续费、印花税、涨跌停判定。
- **实时选股**：输入日期，返回 Top N 候选股。
- **盘后交易信号**：每个交易日 16:00 后给出"明日开盘需执行的操作"清单。
- **Web 可视化**：FastAPI + 单页 HTML + ECharts，画资金曲线、回撤、基准对比。
- **AI 友好**：所有核心逻辑以 `scripts/` 模块形式暴露，配有 type hints + Google-style docstring + CLI，可被 LLM 直接调用。

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 增量更新数据(只补 2026-01-01 至今的日线+流通市值)
python -m scripts.cli update --start 2026-01-01
python -m scripts.cli update --start 2026-01-01 --with-annual

# 3. 跑一次回测(2018-01-01 至今)
python -m scripts.cli backtest --start 2018-01-01 --output data/result.json

# 4. 看今天该买/卖什么
python -m scripts.cli signals --date 2026-06-07 --budget 100000

# 5. 选 Top 5 候选股
python -m scripts.cli select --date 2026-06-07 --num 5

# 6. 启动 Web 服务
python -m scripts.cli serve
# 浏览器打开 http://127.0.0.1:8000
```

## 📁 项目结构

```
quant-cta-trend/
├── scripts/                    # 核心代码(AI 友好,带 CLI 和 docstring)
│   ├── data/                   # 增量数据爬取
│   │   ├── fetch_daily.py
│   │   ├── fetch_market_value.py
│   │   ├── fetch_annual.py     # 可选:同步最新年报
│   │   ├── build_unified.py
│   │   └── update_all.py       # 一键更新入口
│   ├── strategy/               # 策略逻辑
│   │   ├── data_loader.py
│   │   ├── select_stocks.py
│   │   ├── trading_signals.py
│   │   └── backtest.py
│   ├── common.py               # 路径/重试/板块过滤等基础工具
│   └── cli.py                  # CLI 入口
├── web/                        # FastAPI + 单页 HTML
│   ├── backend.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── tests/                      # 单元测试
│   ├── test_common.py
│   ├── test_select_stocks.py
│   └── test_trading_signals.py
├── docs/                       # 详细文档
├── data/                       # 数据(被 .gitignore 排除)
├── code/                       # 原始 Jupyter(只读,已迁移到 scripts/)
├── .gitignore
├── .gitattributes
├── LICENSE
├── requirements.txt
└── README.md
```

## 🧠 策略一句话

> 每周三收盘后基于"主板 + EPS>0 + ROE>10% + 流通市值升序"挑选 5 只股票，周四开盘等权买入（100 股取整），下周三按收盘价卖出（涨停一字板除外）。

详细规则、过滤条件、参数含义见 [`docs/03-stock-selection-strategy.md`](./docs/03-stock-selection-strategy.md)。

## 🛠 CLI 用法

```
python -m scripts.cli <command> [options]

Commands:
  update      增量更新本地数据(默认只补日线+流通市值)
  select      单日选股:返回 Top N 候选股
  signals     盘后交易信号:给出某日"明日开盘需执行的操作"
  backtest    历史回测,输出交易记录 + 评价指标
  serve       启动 Web 服务
```

完整参数：`python -m scripts.cli <command> --help`

## 🧪 测试

```bash
python -m pytest tests/ -v
```

34 个测试覆盖核心逻辑（板块过滤 / 选股 / 信号生成 / 重试 / 涨停跳过）。

## 🤖 给 AI 模型的使用说明

本项目刻意把核心逻辑封装在 `scripts/strategy/*.py`，每个公开函数都带：

- **PEP 484 type hints** —— LLM 能直接理解参数类型
- **Google-style docstring** —— 包含 Args / Returns / Raises / Example
- **`__all__` 显式导出** —— `from scripts.strategy import *` 行为可控
- **可独立运行的 CLI** —— 任何 shell 都能调

典型调用模式：

```python
from scripts.strategy import select_stocks_for_date, get_signals_for_date, run_backtest

# 选股
picks = select_stocks_for_date(date="2026-06-07", num=5)

# 信号
sigs = get_signals_for_date(date="2026-06-07", budget=100_000,
                            held_positions={"600519": 100})
print(sigs.summary)
for a in sigs.buy_list:  print("BUY", a.code, a.shares, a.reason)
for a in sigs.sell_list: print("SELL", a.code, a.shares, a.reason)

# 回测
result = run_backtest(start_date="2018-01-01", end_date="2025-12-31")
print(result.metrics)
```

## ⚠️ 风险提示

- 策略依赖小市值因子，A 股 2017 年后该效应已显著衰减。
- 回测**未考虑**：停牌、涨跌停一字板买入失败、滑点、ST 股 5% 阈值、印花税减半政策。
- 数据来自第三方抓取接口，存在字段缺失 / 接口变动 / 退市股残留风险。
- 本项目**仅供学习与研究**，不构成投资建议。实盘请自行做尽职调查并控制仓位。

## 📚 文档索引

详见 [`docs/README.md`](./docs/README.md)：

- [01 · 项目概览](./docs/01-project-overview.md)
- [02 · 数据流水线](./docs/02-data-pipeline.md)
- [03 · 选股策略](./docs/03-stock-selection-strategy.md)
- [04 · 历史回测](./docs/04-backtest.md)
- [05 · 实时选股](./docs/05-future-stock-selection.md)
- [06 · 数据字典](./docs/06-data-dictionary.md)
- [07 · 已知问题与改进建议](./docs/07-known-issues.md)

## 🔧 进阶：做成 MCP（Model Context Protocol）服务器

如需让 Claude Desktop / Cursor / Cline 等 IDE 直接发现工具，可以加一层 MCP 包装（详见 [`docs/07-known-issues.md`](./docs/07-known-issues.md)）。当前 `scripts/` 的设计已经按 MCP 工具接口的最佳实践编写（type hints + docstring + 单一职责函数），未来加 MCP 包装层只需几行代码：

```python
# 未来扩展:mcp_server.py
from mcp.server import Server
from scripts.strategy import select_stocks_for_date, get_signals_for_date, run_backtest

app = Server("quant-cta-trend")
@app.tool()
def select_stocks(date: str, num: int = 5) -> dict:
    """对某一日选股,返回 Top N 候选股 JSON。"""
    return select_stocks_for_date(date=date, select_stock_num=num).to_dict(orient="records")
```

## 📜 协议

[MIT](./LICENSE) — 包含"不构成投资建议"的免责声明。
