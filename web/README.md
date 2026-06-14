# web/ · FastAPI + 单页 HTML

> 零 npm 依赖、零构建步骤,Python 启动即可使用。

## 启动

```bash
# 方式 1:用 CLI
python -m scripts.cli serve --host 127.0.0.1 --port 8000

# 方式 2:直接 uvicorn
uvicorn web.backend:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。

## 目录结构

```
web/
├── backend.py              # FastAPI 入口(单文件,所有路由)
└── static/
    ├── index.html          # 单页 HTML
    ├── app.js              # Vanilla JS(无构建)
    └── style.css           # 样式
```

## API 端点

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/data/status` | 数据状态(最新日期、股票数等) |
| `GET` | `/api/select?date=&num=&roe=&eps=` | 单日选股 |
| `GET` | `/api/signals?date=&budget=&holdings=` | 盘后交易信号 |
| `POST` | `/api/backtest` | 历史回测 |
| `GET` | `/api/chart/echarts?start=&end=` | ECharts 用的 option JSON |
| `GET` | `/docs` | FastAPI 自动生成的 OpenAPI 文档 |
| `GET` | `/` | 单页 HTML |

## 前端功能

- **选股 Tab**：表单 + 结果表，显示 Top N 候选股（代码/名称/EPS/ROE/市值）。
- **回测 Tab**：参数表单 + ECharts 资金曲线 + 回撤阴影 + 评价指标卡片 + 交易记录表。
- **交易信号 Tab**：分 BUY/SELL/HOLD 三块，附"原因"列（人话解释为什么这样操作）。
- **数据 Tab**：展示当前数据状态 + CLI 更新命令。

## 浏览器打开后第一件事

页面加载时会调 `/api/data/status` 检查数据是否就绪。

- **就绪**：顶部显示"数据: 2018-01-01 ~ 2025-12-31 (X.XM 行)"，可正常选股/回测。
- **未就绪**：显示"统一底表不存在，请先运行 `scripts.cli update`"。

## 部署到生产

可以反向代理到 nginx，或直接用 gunicorn：

```bash
pip install gunicorn
gunicorn web.backend:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

## 添加新指标 / 新图表

后端：
- 在 `web/backend.py` 添加新路由（参考 `/api/backtest`）。
- 如果要返回新图表数据，建议直接给 ECharts 的 option 结构。

前端：
- 在 `web/static/index.html` 加 `<section class="tab-panel" id="tab-xxx">`。
- 在 `web/static/app.js` 加新 tab 的提交逻辑。
- ECharts 通过 CDN 加载（`index.html` 已有），不需要任何构建工具。
