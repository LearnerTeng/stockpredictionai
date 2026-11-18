"""Deterministic local execution-event replay, never a broker connection."""
from decimal import Decimal


def replay_events(events, initial_cash=100000):
    def number(value):
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError('amounts must be finite and nonnegative')
        return result

    cash = number(initial_cash)
    orders, holdings, seen = {}, {}, {}
    for event in events:
        eid = event['event_id']
        if not isinstance(eid, str) or not eid:
            raise ValueError('event_id required')
        if eid in seen:
            if seen[eid] != event:
                raise ValueError('conflicting duplicate event')
            continue
        seen[eid] = dict(event)
        oid, kind = event['order_id'], event['type']
        if kind == 'submit':
            if oid in orders or event['side'] not in ('buy', 'sell'):
                raise ValueError('invalid or duplicate order')
            quantity = number(event['quantity'])
            if quantity == 0 or not event['symbol']:
                raise ValueError('symbol and positive quantity required')
            orders[oid] = dict(symbol=event['symbol'], side=event['side'], quantity=quantity,
                               filled=Decimal(0), status='open')
            continue
        if oid not in orders or orders[oid]['status'] not in ('open', 'partial'):
            raise ValueError('unknown or closed order')
        order = orders[oid]
        if kind == 'cancel':
            order['status'] = 'cancelled'
        elif kind == 'fill':
            quantity, price, fee = number(event['quantity']), number(event['price']), number(event.get('fee', 0))
            if quantity == 0 or price == 0 or order['filled'] + quantity > order['quantity']:
                raise ValueError('invalid fill quantity or price')
            symbol = order['symbol']
            side = 1 if order['side'] == 'buy' else -1
            next_cash = cash - side * quantity * price - fee
            next_shares = holdings.get(symbol, Decimal(0)) + side * quantity
            if next_cash < 0 or next_shares < 0:
                raise ValueError('insufficient cash or shares')
            cash, holdings[symbol] = next_cash, next_shares
            order['filled'] += quantity
            order['status'] = 'filled' if order['filled'] == order['quantity'] else 'partial'
        else:
            raise ValueError('unknown event type')
    return {'cash': str(cash), 'holdings': {key: str(value) for key, value in holdings.items()},
            'orders': {key: {k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()}
                       for key, value in orders.items()}, 'unique_events': len(seen)}


def reconcile_events(events, expected, initial_cash=100000):
    actual = replay_events(events, initial_cash)
    if actual != expected:
        raise ValueError('local event ledger reconciliation failed')
    return actual
