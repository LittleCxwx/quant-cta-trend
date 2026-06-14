"""量化策略 CLI 统一入口。

子命令:
    update      增量更新数据
    select      单日选股
    signals     盘后交易信号
    backtest    历史回测
    serve       启动 Web 服务

用法:
    python -m scripts.cli update --start 2026-01-01
    python -m scripts.cli select --date 2025-12-25 --num 5
    python -m scripts.cli signals --date 2025-12-25 --budget 100000
    python -m scripts.cli backtest --start 2018-01-01 --end 2025-12-31
    python -m scripts.cli serve --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts.common import DATA_DIR, logger


def _cmd_update(args: argparse.Namespace) -> int:
    from scripts.data import update_all
    return update_all.main.__wrapped__([str(a) for a in [
        "--start", args.start,
        "--end", args.end,
        *(["--with-annual"] if args.with_annual else []),
        *(["--reset"] if args.reset else []),
        *(["--codes", *args.codes] if args.codes else []),
    ]]) if False else _call_update(args)


def _call_update(args: argparse.Namespace) -> int:
    """直接调 update_all.main,绕过它内部的 argparse。"""
    from scripts.data import fetch_daily, fetch_market_value, fetch_annual, build_unified
    from scripts.common import ProgressTracker

    logger.info("==== update %s ~ %s ====", args.start, args.end)
    if args.reset:
        ProgressTracker("fetch_daily").reset()
        ProgressTracker("fetch_mv").reset()
        logger.warning("断点续传已重置")

    if not args.skip_daily:
        fetch_daily.run(args.start, args.end, args.codes)
    if not args.skip_mv:
        fetch_market_value.run(args.codes, target_date=args.end)
    if args.with_annual:
        fetch_annual.run(args.codes, args.start)
    if not args.skip_unified:
        build_unified._build_or_append_unified(args.start)
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    from scripts.strategy import select_stocks_for_date
    df = select_stocks_for_date(
        date=args.date,
        select_stock_num=args.num,
        eps_threshold=args.eps,
        roe_threshold=args.roe,
        exclude_st=not args.include_st,
    )
    if args.format == "json":
        print(df.to_json(orient="records", force_ascii=False, indent=2))
    else:
        print(df.to_string(index=False))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False, encoding="utf-8-sig")
        logger.info("已保存到 %s", args.output)
    return 0


def _cmd_signals(args: argparse.Namespace) -> int:
    from scripts.strategy import get_signals_for_date
    held = {}
    if args.holdings:
        # 解析 "code:shares,code:shares"
        for token in args.holdings.split(","):
            c, s = token.split(":")
            held[c.strip()] = int(s)
    sigs = get_signals_for_date(
        date=args.date, select_stock_num=args.num,
        budget=args.budget, held_positions=held or None,
    )
    if args.format == "json":
        print(sigs.to_json(indent=2))
    else:
        print(sigs.summary)
        for a in sigs.buy_list:
            print(f"  🟢 BUY  {a.code} {a.name} {a.shares}股 @¥{a.price}  ({a.reason})")
        for a in sigs.sell_list:
            print(f"  🔴 SELL {a.code} {a.name} {a.shares}股 @¥{a.price}  ({a.reason})")
        for a in sigs.hold_list:
            print(f"  ⚪ HOLD {a.code} {a.name} {a.shares}股  ({a.reason})")
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    from scripts.strategy import run_backtest
    result = run_backtest(
        start_date=args.start, end_date=args.end,
        init_cash=args.cash, select_stock_num=args.num,
        eps_threshold=args.eps, roe_threshold=args.roe,
        c_rate=args.c_rate, t_rate=args.t_rate,
        exclude_st=not args.include_st,
        include_benchmark=not args.no_benchmark,
    )
    print("=" * 60)
    print("📊 回测结果")
    print("=" * 60)
    for k, v in result.metrics.items():
        print(f"  {k:>16}: {v}")
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        result.to_dict()  # 校验可序列化
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("回测结果已保存到 %s", args.output)
    if args.csv:
        import pandas as pd
        pd.DataFrame(result.asset_curve).to_csv(args.csv, index=False, encoding="utf-8-sig")
        logger.info("资金曲线 CSV 已保存到 %s", args.csv)
    if args.trades_csv:
        import pandas as pd
        pd.DataFrame(result.trades).to_csv(args.trades_csv, index=False, encoding="utf-8-sig")
        logger.info("交易记录 CSV 已保存到 %s", args.trades_csv)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """启动 FastAPI Web 服务(委托给 web.backend)。"""
    import uvicorn
    uvicorn.run(
        "web.backend:app",
        host=args.host, port=args.port,
        reload=args.reload, log_level="info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.cli",
        description="A 股小市值轮动策略 CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # update
    p_upd = sub.add_parser("update", help="增量更新数据")
    p_upd.add_argument("--start", default="2026-01-01")
    p_upd.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    p_upd.add_argument("--codes", nargs="*", default=None)
    p_upd.add_argument("--with-annual", action="store_true",
                        help="同步最新年报/中报(慢,默认跳过)")
    p_upd.add_argument("--skip-daily", action="store_true")
    p_upd.add_argument("--skip-mv", action="store_true")
    p_upd.add_argument("--skip-unified", action="store_true")
    p_upd.add_argument("--reset", action="store_true",
                        help="清空断点续传进度")
    p_upd.set_defaults(func=_cmd_update)

    # select
    p_sel = sub.add_parser("select", help="单日选股")
    p_sel.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_sel.add_argument("--num", type=int, default=5)
    p_sel.add_argument("--eps", type=float, default=0.0)
    p_sel.add_argument("--roe", type=float, default=10.0)
    p_sel.add_argument("--include-st", action="store_true",
                        help="不剔除 ST(默认剔除)")
    p_sel.add_argument("--format", choices=["table", "json"], default="table")
    p_sel.add_argument("--output", help="保存到 CSV")
    p_sel.set_defaults(func=_cmd_select)

    # signals
    p_sig = sub.add_parser("signals", help="盘后交易信号")
    p_sig.add_argument("--date", required=True)
    p_sig.add_argument("--num", type=int, default=5)
    p_sig.add_argument("--budget", type=float, default=10_000.0,
                        help="周四买入的预算(元)")
    p_sig.add_argument("--holdings", default=None,
                        help="当前持仓 code:shares,code:shares")
    p_sig.add_argument("--format", choices=["text", "json"], default="text")
    p_sig.set_defaults(func=_cmd_signals)

    # backtest
    p_bt = sub.add_parser("backtest", help="历史回测")
    p_bt.add_argument("--start", default="2018-01-01")
    p_bt.add_argument("--end", default="2025-12-31")
    p_bt.add_argument("--cash", type=float, default=10_000.0)
    p_bt.add_argument("--num", type=int, default=5)
    p_bt.add_argument("--eps", type=float, default=0.0)
    p_bt.add_argument("--roe", type=float, default=10.0)
    p_bt.add_argument("--c-rate", type=float, default=1.2 / 10000)
    p_bt.add_argument("--t-rate", type=float, default=1.0 / 1000)
    p_bt.add_argument("--include-st", action="store_true")
    p_bt.add_argument("--no-benchmark", action="store_true",
                        help="不拉沪深300基准")
    p_bt.add_argument("--output", help="完整 JSON 路径")
    p_bt.add_argument("--csv", help="资金曲线 CSV")
    p_bt.add_argument("--trades-csv", help="交易记录 CSV")
    p_bt.set_defaults(func=_cmd_backtest)

    # serve
    p_srv = sub.add_parser("serve", help="启动 Web 服务")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.add_argument("--reload", action="store_true")
    p_srv.set_defaults(func=_cmd_serve)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
