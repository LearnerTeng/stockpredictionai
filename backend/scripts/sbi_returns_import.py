"""导入 SBI 全期间收益、可选持仓和已匹配基金代码的履历。
Import all-period SBI returns, optional holdings and histories matched by fund code.
"""
import argparse
import csv
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import create_database_engine, session_factory
from trading.sbi_returns import save_report
from scripts.sbi_holdings_snapshot import observed_timestamp


def read_csv(path):
    with path.open("rb") as file:
        raw = file.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("CSV exceeds 1 MB")
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("returns", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="SBI 算出日 (YYYY-MM-DD)")
    parser.add_argument("--total", type=int, required=True, help="SBI トータルリターン (全期間) in JPY")
    parser.add_argument("--holdings", type=Path)
    parser.add_argument("--funds", type=Path, help="JSON keyed by fund code, with name and optional history path")
    parser.add_argument("--portfolio", default="nisa")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_database_engine(connect_args={"connect_timeout": 4})
    try:
        mapping = json.loads(args.funds.read_text(encoding="utf-8-sig")) if args.funds else {}
        names = {code: entry["name"] for code, entry in mapping.items()}
        history = {code: read_csv(args.funds.parent / entry["history"])
                   for code, entry in mapping.items() if entry.get("history")}
        result = save_report(session_factory(engine), args.portfolio, args.as_of, read_csv(args.returns), args.total,
                             read_csv(args.holdings) if args.holdings else None, names, history, args.apply,
                             observed_timestamp(args.holdings.name) if args.holdings else None)
        print(json.dumps(dict(mode="apply" if args.apply else "preview", **result), ensure_ascii=False))
    except (ValueError, csv.Error, OSError, KeyError) as error:
        parser.exit(1, f"SBI report rejected: {error}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
