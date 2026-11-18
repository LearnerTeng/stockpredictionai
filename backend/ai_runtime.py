"""管理账户共享配额，在发起网络请求前提交额度预留。
Manage shared account quotas and commit reservations before making network requests.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from uuid import uuid4
from functools import lru_cache
import json
from sqlalchemy import select, text
from database.models import AppSetting, AiCall
from database.session import create_database_engine, session_factory

DEFAULTS = dict(enabled=False, interval_seconds=60, rpm=40, target_rpm=36,
                background_rpm=28, concurrency=2, position_limit=.25,
                allocation_targets={}, keyword_only=True)

@lru_cache(maxsize=1)
def sessions():
    return session_factory(create_database_engine())

def settings(factory=None):
    with (factory or sessions())() as s:
        row = s.get(AppSetting, 'ai_settings')
        return {**DEFAULTS, **(json.loads(row.value_json) if row else {})}

def save_settings(payload, factory=None):
    factory = factory or sessions()
    if not isinstance(payload, dict) or set(payload) - set(DEFAULTS):
        raise ValueError('Unknown settings')
    value = {**settings(factory), **payload}
    for key in ('enabled', 'keyword_only'):
        if not isinstance(value[key], bool):
            raise ValueError('Boolean setting required')
    for key in ('interval_seconds', 'rpm', 'target_rpm', 'background_rpm', 'concurrency'):
        if type(value[key]) is not int:
            raise ValueError('Integer setting required')
    if not (60 <= value['interval_seconds'] <= 86400 and
            1 <= value['background_rpm'] <= value['target_rpm'] <= value['rpm'] <= 40 and
            1 <= value['concurrency'] <= 2 and 0 < value['position_limit'] <= .25):
        raise ValueError('Invalid limits')
    if not isinstance(value['allocation_targets'], dict) or any(
        not isinstance(v, (float, int)) or isinstance(v, bool) or not 0 < v <= 1
        for v in value['allocation_targets'].values()):
        raise ValueError('Allocation targets must be fractions in (0,1]')
    with factory.begin() as s:
        s.merge(AppSetting(key='ai_settings', value_json=json.dumps(value), updated_at=datetime.now(timezone.utc)))
    return value

class QuotaWait(RuntimeError):
    def __init__(self, seconds=60):
        self.seconds = max(1, seconds)
        super().__init__('Model capacity is temporarily unavailable')

def reserve(task, model, factory=None):
    factory = factory or sessions()
    cfg = settings(factory)
    background = task in ('sentiment', 'deepseek', 'ultra', 'advice_background')
    now = datetime.now(timezone.utc)
    with factory.begin() as s:
        if s.bind.dialect.name != 'postgresql':
            raise RuntimeError('PostgreSQL is required for shared NVIDIA quotas')
        s.execute(text('SELECT pg_advisory_xact_lock(73410591)'))
        cooldown = s.get(AppSetting, 'nvidia_cooldown')
        if cooldown and float(cooldown.value_json) > now.timestamp():
            raise QuotaWait(float(cooldown.value_json) - now.timestamp())
        recent = s.scalars(select(AiCall).where(AiCall.started_at > now - timedelta(seconds=60))).all()
        active = s.scalars(select(AiCall).where(AiCall.status == 'running', AiCall.lease_until > now)).all()
        if len(recent) >= cfg['target_rpm'] or len(active) >= cfg['concurrency'] or (
            background and sum(r.background for r in recent) >= cfg['background_rpm']):
            raise QuotaWait(5)
        identity = uuid4().hex
        s.add(AiCall(id=identity, task=task, model=model, background=background,
                     started_at=now, lease_until=now + timedelta(seconds=150), status='running', tokens=0))
    return identity

def finish(identity, status, tokens=0, retry_after=None, factory=None):
    factory = factory or sessions()
    with factory.begin() as s:
        row = s.get(AiCall, identity)
        row.status, row.tokens, row.finished_at = status, tokens, datetime.now(timezone.utc)
        if retry_after is not None:
            s.execute(text('SELECT pg_advisory_xact_lock(73410591)'))
            old = s.get(AppSetting, 'nvidia_cooldown')
            until = max(float(old.value_json) if old else 0,
                        datetime.now(timezone.utc).timestamp() + retry_after)
            s.merge(AppSetting(key='nvidia_cooldown', value_json=str(until), updated_at=datetime.now(timezone.utc)))

def retry_seconds(error):
    header = getattr(getattr(error, 'response', None), 'headers', {}).get('Retry-After', '60')
    try:
        return max(1, float(header))
    except ValueError:
        try:
            return max(1, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError):
            return 60
