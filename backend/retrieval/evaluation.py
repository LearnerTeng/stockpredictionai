from statistics import mean


def evaluate(store, cases, mode, k=5):
    rows = []
    for case in cases:
        response = store.search(case['query'], mode=mode, limit=k)
        retrieved = [item['article_id'] for item in response['items']]
        relevant = set(case['relevant'])
        hits = relevant.intersection(retrieved)
        ranks = [i for i, item in enumerate(retrieved, 1) if item in relevant]
        rows.append({'query': case['query'], 'retrieved': retrieved,
            'precision': len(hits) / k,
            'recall': len(hits) / len(relevant) if relevant else None,
            'reciprocal_rank': 1 / min(ranks) if ranks else 0,
            'empty_correct': not retrieved if not relevant else None,
            'elapsed_ms': response['elapsed_ms'], 'query_tokens': response['query_tokens']})
    positives = [r for r in rows if r['recall'] is not None]
    negatives = [r for r in rows if r['empty_correct'] is not None]
    latency = sorted(r['elapsed_ms'] for r in rows)
    return {'mode': mode, 'k': k, 'queries': len(rows),
        'precision_at_k': mean(r['precision'] for r in rows) if rows else None,
        'recall_at_k': mean(r['recall'] for r in positives) if positives else None,
        'mrr': mean(r['reciprocal_rank'] for r in positives) if positives else None,
        'no_answer_accuracy': mean(r['empty_correct'] for r in negatives) if negatives else None,
        'p95_ms': latency[min(len(latency)-1, int(.95*len(latency)))] if latency else None,
        'query_tokens': sum(r['query_tokens'] for r in rows), 'observations': rows}
