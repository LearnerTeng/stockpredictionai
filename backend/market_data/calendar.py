"""Exchange sessions, including holidays, early closes and DST."""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xcals

MARKETS = {"US": "XNYS", "JP": "XTKS", "HK": "XHKG"}


@lru_cache(maxsize=24)
def calendar(market="US", year=2026):
    if market not in MARKETS:
        raise ValueError("unsupported exchange market")
    return xcals.get_calendar(MARKETS[market], start="1997-01-01", end=f"{max(year+1, 2035)}-12-31")


def session_close(day: date, market="US") -> datetime:
    return calendar(market, day.year).session_close(day.isoformat()).to_pydatetime()


def next_session(day: date, market="US") -> date:
    return calendar(market, day.year).date_to_session((day + timedelta(days=1)).isoformat(), direction="next").date()


def available_session(moment: datetime, market="US") -> date:
    if moment.tzinfo is None:
        raise ValueError("availability timestamp must include a timezone")
    cal = calendar(market, moment.year)
    day = cal.date_to_session(moment.astimezone(cal.tz).date().isoformat(), direction="next").date()
    return next_session(day, market) if moment > session_close(day, market) else day


def latest_completed_session(moment: datetime, market="US") -> date:
    if moment.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    cal = calendar(market, moment.year)
    day = cal.date_to_session(moment.astimezone(cal.tz).date().isoformat(), direction="previous")
    if moment.astimezone(timezone.utc) < cal.session_close(day).to_pydatetime():
        day = cal.previous_session(day)
    return day.date()
