from datetime import datetime, timezone
import json
from flask import Blueprint, jsonify, request
from sqlalchemy import select
from database.models import AppSetting
from .model_lines import NewsModelLines
from stock_ai.news_comparison import run_comparison
from stock_ai.sentiment_eval import evaluate_sentiment
from stock_ai.portfolio_backtest import PortfolioBacktestConfig


def register_line_api(app, require_sentiment, trading_store):
    api = Blueprint('news_lines', __name__)

    @api.get('/sentiment/lines')
    def status():
        try:
            store, _ = require_sentiment()
            with store.sessions() as session:
                saved = session.get(AppSetting, 'news_model_enabled')
                enabled = json.loads(saved.value_json) if saved else []
                reports = session.scalars(select(AppSetting).where(AppSetting.key.like('news-comparison:%'))
                    .order_by(AppSetting.updated_at.desc()).limit(1)).all()
                reports = [json.loads(r.value_json) for r in reports]
            return jsonify(models=NewsModelLines(store.sessions).status(), enabled=enabled, comparisons=reports)
        except Exception:
            return jsonify(error='News simulation database unavailable; check migrations'), 503

    @api.post('/sentiment/lines')
    def enable():
        try:
            payload = request.get_json()
            lines = payload['lines']
            if not isinstance(lines, list) or len(lines) > 2 or any(l not in ('deepseek', 'ultra') for l in lines):
                raise ValueError('select deepseek and/or ultra')
            store, _ = require_sentiment()
            with store.sessions.begin() as session:
                row = session.get(AppSetting, 'news_model_enabled')
                if row is None:
                    session.add(AppSetting(key='news_model_enabled', value_json=json.dumps(lines), updated_at=datetime.now(timezone.utc)))
                else:
                    row.value_json, row.updated_at = json.dumps(lines), datetime.now(timezone.utc)
            queued = NewsModelLines(store.sessions).enqueue(lines) if lines else 0
            return jsonify(queued=queued, enabled=lines)
        except (ValueError, KeyError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='News model queue unavailable'), 503

    @api.post('/sentiment/lines/compare')
    def compare():
        try:
            payload = request.get_json()
            store, _ = require_sentiment()
            report = run_comparison(store.sessions, payload['dataset'], payload['lines'],
                                    PortfolioBacktestConfig(**payload.get('config', {})))
            with store.sessions.begin() as session:
                key = 'news-comparison:' + report['id']
                if session.get(AppSetting, key) is None:
                    session.add(AppSetting(key=key, value_json=json.dumps(report, allow_nan=False), updated_at=datetime.now(timezone.utc)))
            return jsonify(report)
        except (ValueError, KeyError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='News comparison unavailable; check database and input data'), 503

    @api.route('/sentiment/lines/evaluation', methods=['GET', 'POST'])
    def evaluation():
        try:
            store, _ = require_sentiment()
            if request.method == 'GET':
                with store.sessions() as session:
                    reports = session.scalars(select(AppSetting).where(AppSetting.key.like('sentiment-eval:%'))
                        .order_by(AppSetting.updated_at.desc()).limit(1)).all()
                    return jsonify(report=json.loads(reports[0].value_json) if reports else None)
            report = evaluate_sentiment(store.sessions, request.get_json())
            with store.sessions.begin() as session:
                key = 'sentiment-eval:' + report['id']
                session.merge(AppSetting(key=key, value_json=json.dumps(report, allow_nan=False),
                                         updated_at=datetime.now(timezone.utc)))
            return jsonify(report)
        except (ValueError, KeyError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Evaluation unavailable; check database, migrations and research dependencies'), 503

    @api.get('/sentiment/lines/holdings')
    def holdings():
        try:
            portfolio = trading_store.get_portfolio(request.args.get('portfolio_id', 'primary'))
            return jsonify(as_of=datetime.now(timezone.utc).isoformat(), portfolio=portfolio)
        except ValueError:
            return jsonify(error='Portfolio not found'), 404

    app.register_blueprint(api)
