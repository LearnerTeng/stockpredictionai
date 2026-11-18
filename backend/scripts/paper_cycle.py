"""Run one local paper checkpoint from a frozen, point-in-time dataset."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import create_database_engine, session_factory
from stock_ai.paper_cycle import run_paper_cycle, archived_signals
from stock_ai.portfolio_backtest import PortfolioBacktestConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--strategy', default='research')
    parser.add_argument('--registry', type=Path, help='Attach recorded forward predictions from this trusted model registry')
    parser.add_argument('--horizon', type=int, choices=[5, 20], default=5)
    args = parser.parse_args()
    payload = json.loads(args.dataset.read_text(encoding='utf-8'))
    dataset = payload.get('dataset', payload)
    if args.registry:
        dataset['signals'] = archived_signals(args.registry, dataset['assets'], args.horizon)
    engine = create_database_engine()
    try:
        report = run_paper_cycle(session_factory(engine), dataset,
            strategy=args.strategy, config=PortfolioBacktestConfig(**payload.get('config', {})))
        print(json.dumps({key: value for key, value in report.items() if key not in ('dataset', 'result')}, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
