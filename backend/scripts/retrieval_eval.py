"""Evaluate a fixed corpus in a disposable schema; never indexes production news."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.schema import CreateSchema, DropSchema
from database.models import Base
from database.session import session_factory
from sentiment.store import SentimentStore
from retrieval.store import RetrievalStore
from retrieval.evaluation import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--modes', nargs='+', choices=['keyword', 'vector', 'hybrid'], default=['keyword'])
    args = parser.parse_args()
    url = os.environ.get('RETRIEVAL_EVAL_DATABASE_URL')
    if not url:
        parser.error('set RETRIEVAL_EVAL_DATABASE_URL to a dedicated PostgreSQL evaluation database')
    corpus = json.loads(args.corpus.read_text(encoding='utf-8'))
    store = SentimentStore(url)
    if store.engine.dialect.name != 'postgresql':
        parser.error('pgvector-enabled PostgreSQL required')
    schema = 'retrieval_eval_' + uuid4().hex
    with store.engine.begin() as conn:
        conn.execute(CreateSchema(schema))
    store.engine = store.engine.execution_options(schema_translate_map={None: schema})
    store.sessions = session_factory(store.engine)
    try:
        Base.metadata.create_all(store.engine)
        for row in corpus['documents']:
            store.upsert_article(dict(id=row['id'], content_hash=row['id'], title=row['text'],
                source='synthetic-evaluation', provider='fixture', provider_item_id=row['id'],
                published_at=datetime.now(timezone.utc)-timedelta(days=1), symbols=[]))
        retrieval = RetrievalStore(store.sessions)
        indexing = {'tokens': 0}
        if any(mode != 'keyword' for mode in args.modes):
            retrieval.enqueue()
            indexing = retrieval.process(limit=len(corpus['documents']))
            if indexing['failed']:
                raise RuntimeError('embedding failed; evaluation must not report partial corpus metrics')
        print(json.dumps({'corpus': corpus['version'], 'description': corpus['description'],
            'embedding_model': retrieval.embedder.version, 'indexing': indexing,
            'results': [evaluate(retrieval, corpus['queries'], mode) for mode in args.modes]}, indent=2))
    finally:
        assert schema.startswith('retrieval_eval_') and len(schema) == 47
        with store.engine.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        store.engine.dispose()


if __name__ == '__main__':
    main()
