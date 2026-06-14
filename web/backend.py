"""FastAPI 后端入口。

启动:
    python -m scripts.cli serve
    # 或
    uvicorn web.backend:app --reload --port 8000

API:
    GET  /                        # 静态首页
    GET  /api/health              # 健康检查
    GET  /api/data/status         # 数据状态(最新日期、股票数等)
    GET  /api/select?date=YYYY-MM-DD&num=5
    GET  /api/signals?date=YYYY-MM-DD&budget=10000
    POST /api/backtest            # Body: {start, end, num, cash, ...}
    GET  /api/chart/echarts?start=YYYY-MM-DD&end=YYYY-MM-DD
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scripts.common import (
    DATA_DIR,
    STOCK_LIST_CSV,
    UNIFIED_CSV,
    logger,
)

# ===== 静态文件目录 =====
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"

# ===== FastAPI app =====
app = FastAPI(
    title="量化策略 Web",
    description="A 股小市值轮动策略 · 选股 / 回测 / 交易信号",
    version="0.1.0",
)

# 允许本地前端直连(开发用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)


# ===== 辅助:把单日截面转成 dict(给前端)=====
def _df_to_records(df, columns: list[str] | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    df = df.copy()
    for c in df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        df[c] = df[c].dt.strftime("%Y-%m-%d")
    return df.fillna("").to_dict(orient="records")


# ===== 路由 =====
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "ts": datetime.now().isoformat()}


@app.get("/api/data/status")
def data_status() -> dict:
    """返回当前数据状态(用于前端判断"数据是否更新")。"""
    info: dict = {
        "unified_exists": UNIFIED_CSV.exists(),
        "unified_path": str(UNIFIED_CSV),
        "stock_list_exists": STOCK_LIST_CSV.exists(),
    }
    if info["unified_exists"]:
        try:
            import pandas as pd
            # 只读一列,快速拿 max date
            df = pd.read_csv(UNIFIED_CSV, usecols=["日期"], dtype={"日期": "string"})
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            max_d = df["日期"].max()
            min_d = df["日期"].min()
            info["unified_rows"] = len(df)
            info["unified_max_date"] = max_d.strftime("%Y-%m-%d") if pd.notna(max_d) else None
            info["unified_min_date"] = min_d.strftime("%Y-%m-%d") if pd.notna(min_d) else None
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
    return info


@app.get("/api/select")
def api_select(
    date: str = Query(..., description="目标日期 YYYY-MM-DD"),
    num: int = Query(5, ge=1, le=20),
    eps: float = Query(0.0),
    roe: float = Query(10.0),
    include_st: bool = Query(False),
) -> dict:
    """单日选股。"""
    try:
        from scripts.strategy import select_stocks_for_date
        df = select_stocks_for_date(
            date=date, select_stock_num=num,
            eps_threshold=eps, roe_threshold=roe,
            exclude_st=not include_st,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "date": date,
        "base_date": None,
        "num": num,
        "picks": _df_to_records(df, [
            "股票代码", "名称", "EPSJB", "ROEJQ",
            "收盘", "流通市值", "选股权重",
        ]),
    }


@app.get("/api/signals")
def api_signals(
    date: str = Query(..., description="信号日 YYYY-MM-DD"),
    num: int = Query(5, ge=1, le=20),
    budget: float = Query(10_000.0, gt=0),
    holdings: Optional[str] = Query(None, description="code:shares,code:shares"),
) -> dict:
    """盘后交易信号。"""
    held = None
    if holdings:
        try:
            held = {c.strip(): int(s) for c, s in (t.split(":") for t in holdings.split(","))}
        except ValueError:
            raise HTTPException(400, "holdings 格式错误,应为 code:shares,code:shares")
    try:
        from scripts.strategy import get_signals_for_date
        sigs = get_signals_for_date(date=date, select_stock_num=num, budget=budget, held_positions=held)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sigs.to_dict()


class BacktestRequest(BaseModel):
    start: str = Field("2018-01-01")
    end: str = Field("2025-12-31")
    num: int = Field(5, ge=1, le=20)
    cash: float = Field(10_000.0, gt=0)
    eps: float = Field(0.0)
    roe: float = Field(10.0)
    c_rate: float = Field(1.2 / 10000)
    t_rate: float = Field(1.0 / 1000)
    include_st: bool = Field(False)
    no_benchmark: bool = Field(False)


@app.post("/api/backtest")
def api_backtest(req: BacktestRequest) -> dict:
    """历史回测(POST 因为参数较多)。"""
    try:
        from scripts.strategy import run_backtest
        result = run_backtest(
            start_date=req.start, end_date=req.end,
            init_cash=req.cash, select_stock_num=req.num,
            eps_threshold=req.eps, roe_threshold=req.roe,
            c_rate=req.c_rate, t_rate=req.t_rate,
            exclude_st=not req.include_st,
            include_benchmark=not req.no_benchmark,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("回测失败")
        raise HTTPException(status_code=500, detail=f"回测失败: {e}")
    return result.to_dict()


@app.get("/api/chart/echarts")
def api_echarts(
    start: str = Query("2018-01-01"),
    end: str = Query("2025-12-31"),
    num: int = Query(5),
    cash: float = Query(10_000.0),
) -> dict:
    """返回 ECharts 用的 JSON(option 结构)。"""
    try:
        from scripts.strategy import run_backtest
        result = run_backtest(
            start_date=start, end_date=end,
            init_cash=cash, select_stock_num=num,
            include_benchmark=True,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"回测失败: {e}")

    return _build_echarts_option(result)


def _build_echarts_option(result) -> dict:
    """把 BacktestResult 转成 ECharts 标准 option。"""
    curve = result.asset_curve
    dates = [r["date"] for r in curve]
    assets = [r["total_asset"] for r in curve]
    benches = [r.get("bench_value") for r in curve]
    drawdowns = [r["drawdown"] * 100 for r in curve]  # 百分比

    # 标记买入 / 卖出点
    buy_pts = [{"coord": [t["date"], t["price"]], "value": "B"}
               for t in result.trades if t["action"] == "buy"]
    sell_pts = [{"coord": [t["date"], t["price"]], "value": "S"}
                for t in result.trades if t["action"] == "sell"]

    return {
        "title": {"text": "策略资金 & 回撤 vs 沪深300", "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "legend": {"top": 30},
        "grid": [
            {"left": 60, "right": 60, "top": 80, "height": "55%"},
            {"left": 60, "right": 60, "top": "72%", "height": "20%"},
        ],
        "xAxis": [
            {"type": "category", "data": dates, "gridIndex": 0},
            {"type": "category", "data": dates, "gridIndex": 1},
        ],
        "yAxis": [
            {"name": "资金(元)", "gridIndex": 0},
            {"name": "回撤(%)", "gridIndex": 1},
        ],
        "dataZoom": [
            {"type": "inside", "xAxisIndex": [0, 1]},
            {"type": "slider", "xAxisIndex": [0, 1]},
        ],
        "series": [
            {
                "name": "策略总资产",
                "type": "line", "data": assets, "smooth": True,
                "lineStyle": {"color": "#1f77b4", "width": 2},
                "markPoint": {"data": buy_pts[:200], "symbol": "triangle",
                              "symbolSize": 6, "itemStyle": {"color": "red"}},
            },
            {
                "name": "沪深300",
                "type": "line", "data": benches, "smooth": True,
                "lineStyle": {"color": "#ff7f0e", "width": 1.5},
            },
            {
                "name": "回撤",
                "type": "line", "xAxisIndex": 1, "yAxisIndex": 1,
                "data": drawdowns,
                "lineStyle": {"color": "red", "width": 1},
                "areaStyle": {"color": "rgba(255,0,0,0.1)"},
            },
        ],
    }


# ===== 静态首页 =====
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    if not INDEX_HTML.exists():
        raise HTTPException(404, f"index.html 不存在: {INDEX_HTML}")
    return FileResponse(str(INDEX_HTML))
