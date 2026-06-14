# 文档索引

> 详细的项目文档,按主题分文件。

| 文档 | 内容 |
| --- | --- |
| [01 · 项目概览](./01-project-overview.md) | 目标、目录结构、依赖、运行流程 |
| [02 · 数据流水线](./02-data-pipeline.md) | `main.ipynb` 各阶段：股票池筛选、日线下载、年报 / 流通市值合并 |
| [03 · 选股策略](./03-stock-selection-strategy.md) | 板块过滤、基本面过滤、小市值排序、`select_stocks` 实现 |
| [04 · 历史回测](./04-backtest.md) | `选股.ipynb` 的撮合逻辑、手续费、评价指标、画图 |
| [05 · 实时选股](./05-future-stock-selection.md) | `未来选股.ipynb` 的单日选股封装 |
| [06 · 数据字典](./06-data-dictionary.md) | 各 CSV / TXT 文件的字段说明 |
| [07 · 已知问题与改进建议](./07-known-issues.md) | 现状缺陷、潜在 bug、可重构方向 |
| [08 · 新版架构（scripts/web）](./08-new-architecture.md) | 重构后的代码组织、CLI、Web、AI 接口 |

## 新增内容（2026-06 重构）

为支持**快速增量更新**、**Web 可视化**和**AI 友好**，项目新增：

- `scripts/` — AI 友好的核心代码库，带 CLI 和 docstring
- `web/` — FastAPI + 单页 HTML + ECharts 可视化
- `tests/` — 34 个单元测试
- 标准 Git 文件（`.gitignore` / `.gitattributes` / `LICENSE` / `requirements.txt`）

详见 [08 · 新版架构](./08-new-architecture.md)。
