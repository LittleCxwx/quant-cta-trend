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

from scripts.common import DATA_DIR, logger, normalize_code


DEFAULT_POSITIONS_FILE = DATA_DIR / "positions.json"
PositionRecord = dict[str, int | float | str | None]


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


def _parse_holdings(text: str | None) -> dict[str, int]:
    """解析 CLI 持仓字符串: code:shares,code:shares。"""
    if not text:
        return {}

    positions: dict[str, int] = {}
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            code, shares = token.split(":", maxsplit=1)
            shares_int = int(shares.strip())
        except ValueError as exc:
            raise ValueError("holdings 格式错误,应为 code:shares,code:shares") from exc
        if shares_int < 0:
            raise ValueError("holdings 股数不能为负数")
        if shares_int == 0:
            continue
        positions[normalize_code(code)] = shares_int
    return positions


def _position_records_to_holdings(records: dict[str, PositionRecord]) -> dict[str, int]:
    """从持仓明细中提取策略只需要的 code -> shares。"""
    return {
        code: int(record["shares"])
        for code, record in records.items()
        if int(record.get("shares") or 0) > 0
    }


def _normalize_position_records(raw: dict) -> dict[str, PositionRecord]:
    """校验并规范化 JSON 持仓明细,兼容旧格式 {"000001": 100}。"""
    records: dict[str, PositionRecord] = {}
    for code, value in raw.items():
        code_str = str(code).strip()
        if not code_str:
            raise ValueError("positions 文件包含空股票代码")
        record: PositionRecord = {}
        if isinstance(value, dict):
            if "shares" not in value:
                raise ValueError(f"positions 文件中 {code_str} 缺少 shares")
            shares = value["shares"]
            name = value.get("name")
            cost_price = value.get("cost_price")
            cost_amount = value.get("cost_amount")
        else:
            shares = value
            name = None
            cost_price = None
            cost_amount = None

        try:
            shares_int = int(shares)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"positions 文件中 {code_str} 的股数不是整数") from exc
        if shares_int < 0:
            raise ValueError(f"positions 文件中 {code_str} 的股数不能为负数")
        if shares_int == 0:
            continue

        record["shares"] = shares_int
        if name:
            record["name"] = str(name)

        cost_price_float: float | None = None
        cost_amount_float: float | None = None
        if cost_price is not None:
            try:
                cost_price_float = float(cost_price)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"positions 文件中 {code_str} 的 cost_price 不是数字") from exc
            if cost_price_float < 0:
                raise ValueError(f"positions 文件中 {code_str} 的 cost_price 不能为负数")
        if cost_amount is not None:
            try:
                cost_amount_float = float(cost_amount)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"positions 文件中 {code_str} 的 cost_amount 不是数字") from exc
            if cost_amount_float < 0:
                raise ValueError(f"positions 文件中 {code_str} 的 cost_amount 不能为负数")

        if cost_price_float is None and cost_amount_float is not None:
            cost_price_float = cost_amount_float / shares_int
        if cost_amount_float is None and cost_price_float is not None:
            cost_amount_float = cost_price_float * shares_int
        if cost_price_float is not None:
            record["cost_price"] = round(cost_price_float, 4)
        if cost_amount_float is not None:
            record["cost_amount"] = round(cost_amount_float, 2)

        records[normalize_code(code_str)] = record
    return records


def _normalize_positions(raw: dict) -> dict[str, int]:
    """校验并规范化 JSON 持仓映射。"""
    return _position_records_to_holdings(_normalize_position_records(raw))


def _load_positions(path: Path) -> dict[str, int]:
    """从 JSON 文件读取持仓。支持 {"000001": 100} 或 {"positions": {...}}。"""
    return _position_records_to_holdings(_load_position_records(path))


def _load_position_records(path: Path) -> dict[str, PositionRecord]:
    """从 JSON 文件读取持仓明细。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"positions 文件不是合法 JSON: {path}") from exc

    if isinstance(raw, dict) and "positions" in raw and isinstance(raw["positions"], dict):
        raw = raw["positions"]
    if not isinstance(raw, dict):
        raise ValueError("positions 文件格式错误,应为 {\"000001\": 100}")
    return _normalize_position_records(raw)


def _save_positions(path: Path, positions: dict[str, int]) -> None:
    """保存持仓 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(sorted(_normalize_positions(positions).items()))
    path.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_position_records(path: Path, records: dict[str, PositionRecord]) -> None:
    """保存带成本的持仓明细 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(sorted(_normalize_position_records(records).items()))
    path.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _apply_signals_to_positions(
    held_positions: dict[str, int],
    sigs,
) -> dict[str, int]:
    """按买卖信号更新持仓。卖出移除/扣减,买入累加,无法卖出的 hold 保留。"""
    positions = dict(held_positions)

    for action in sigs.sell_list:
        shares = int(action.shares)
        if shares <= 0:
            continue
        code = normalize_code(action.code)
        remain = positions.get(code, 0) - shares
        if remain > 0:
            positions[code] = remain
        else:
            positions.pop(code, None)

    for action in sigs.buy_list:
        shares = int(action.shares)
        if shares <= 0:
            continue
        code = normalize_code(action.code)
        positions[code] = positions.get(code, 0) + shares

    return dict(sorted((c, s) for c, s in positions.items() if s > 0))


def _apply_signals_to_position_records(
    position_records: dict[str, PositionRecord],
    sigs,
) -> dict[str, PositionRecord]:
    """按买卖信号更新持仓明细,并在买入时记录均价成本。"""
    records = _normalize_position_records(position_records)

    for action in sigs.sell_list:
        shares = int(action.shares)
        if shares <= 0:
            continue
        code = normalize_code(action.code)
        record = records.get(code)
        if not record:
            continue
        held_shares = int(record["shares"])
        remain = held_shares - shares
        if remain <= 0:
            records.pop(code, None)
            continue
        record["shares"] = remain
        cost_price = record.get("cost_price")
        if cost_price is not None:
            record["cost_amount"] = round(float(cost_price) * remain, 2)
        records[code] = record

    for action in sigs.buy_list:
        shares = int(action.shares)
        if shares <= 0:
            continue
        code = normalize_code(action.code)
        price = float(action.price) if action.price is not None else None
        amount = float(action.amount) if action.amount else (
            price * shares if price is not None else None
        )
        record = records.get(code, {"shares": 0})
        old_shares = int(record.get("shares") or 0)
        new_shares = old_shares + shares
        record["shares"] = new_shares
        if action.name:
            record["name"] = action.name

        old_cost_amount = record.get("cost_amount")
        if old_shares == 0 and amount is not None:
            record["cost_amount"] = round(amount, 2)
            record["cost_price"] = round(amount / shares, 4)
        elif old_cost_amount is not None and amount is not None:
            new_cost_amount = float(old_cost_amount) + amount
            record["cost_amount"] = round(new_cost_amount, 2)
            record["cost_price"] = round(new_cost_amount / new_shares, 4)
        else:
            record.pop("cost_amount", None)
            record.pop("cost_price", None)
        records[code] = record

    return dict(sorted(records.items()))


def _sell_pnl_text(action, position_records: dict[str, PositionRecord]) -> str:
    """生成卖出动作的估算盈亏说明。"""
    code = normalize_code(action.code)
    record = position_records.get(code)
    if not record or record.get("cost_price") is None:
        return "估算盈亏: 成本未知"
    if action.price is None:
        return "估算盈亏: 卖出参考价未知"

    shares = int(action.shares)
    cost_price = float(record["cost_price"])
    cost_amount = cost_price * shares
    sell_amount = float(action.price) * shares
    pnl = sell_amount - cost_amount
    pnl_pct = pnl / cost_amount * 100 if cost_amount else 0.0
    label = "盈利" if pnl >= 0 else "亏损"
    return f"估算{label} ¥{abs(pnl):.2f} ({pnl_pct:+.2f}%, 成本 ¥{cost_price:.2f})"


def _signals_dict_with_pnl(sigs, position_records: dict[str, PositionRecord]) -> dict:
    """给 JSON 输出补充卖出盈亏字段。"""
    data = sigs.to_dict()
    for action in data["sell_list"]:
        code = normalize_code(action["code"])
        record = position_records.get(code)
        price = action.get("price")
        shares = int(action.get("shares") or 0)
        if not record or record.get("cost_price") is None or price is None or shares <= 0:
            action["pnl_status"] = "unknown"
            action["pnl_reason"] = "成本未知" if not record or record.get("cost_price") is None else "卖出参考价未知"
            continue
        cost_price = float(record["cost_price"])
        cost_amount = cost_price * shares
        sell_amount = float(price) * shares
        pnl = sell_amount - cost_amount
        action["cost_price"] = round(cost_price, 4)
        action["cost_amount"] = round(cost_amount, 2)
        action["pnl"] = round(pnl, 2)
        action["pnl_pct"] = round(pnl / cost_amount * 100, 4) if cost_amount else 0.0
        action["pnl_status"] = "profit" if pnl >= 0 else "loss"
    return data


def _positions_file_arg(path_arg: str | None) -> Path:
    return Path(path_arg) if path_arg else DEFAULT_POSITIONS_FILE


def _cmd_signals(args: argparse.Namespace) -> int:
    from scripts.strategy import get_signals_for_date

    positions_file = _positions_file_arg(args.positions_file)
    position_records: dict[str, PositionRecord] = {}
    held: dict[str, int] = {}
    if args.positions_file or args.save_positions:
        if positions_file.exists():
            try:
                position_records.update(_load_position_records(positions_file))
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            held.update(_position_records_to_holdings(position_records))
            logger.info("已读取持仓 %s: %d 只", positions_file, len(held))
        elif not args.save_positions:
            print(f"positions 文件不存在: {positions_file}", file=sys.stderr)
            return 2

    try:
        cli_holdings = _parse_holdings(args.holdings)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    held.update(cli_holdings)
    for code, shares in cli_holdings.items():
        position_records[code] = {"shares": shares}

    sigs = get_signals_for_date(
        date=args.date, select_stock_num=args.num,
        budget=args.budget, held_positions=held or None,
    )
    if args.format == "json":
        print(json.dumps(_signals_dict_with_pnl(sigs, position_records), ensure_ascii=False, indent=2))
    else:
        print(sigs.summary)
        for a in sigs.buy_list:
            print(f"  🟢 BUY  {a.code} {a.name} {a.shares}股 @¥{a.price}  ({a.reason})")
        for a in sigs.sell_list:
            pnl_text = _sell_pnl_text(a, position_records)
            print(f"  🔴 SELL {a.code} {a.name} {a.shares}股 @¥{a.price}  ({a.reason}; {pnl_text})")
        for a in sigs.hold_list:
            print(f"  ⚪ HOLD {a.code} {a.name} {a.shares}股  ({a.reason})")
    if args.save_positions:
        updated = _apply_signals_to_position_records(position_records, sigs)
        try:
            _save_position_records(positions_file, updated)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        logger.info("已保存持仓到 %s: %d 只", positions_file, len(updated))
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
    p_sig.add_argument("--positions-file", default=None,
                        help="持仓 JSON 文件,支持 {\"000001\": 100} 或带 cost_price 的明细")
    p_sig.add_argument("--save-positions", action="store_true",
                        help="按本次买卖信号更新并保存持仓(默认 data/positions.json)")
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
