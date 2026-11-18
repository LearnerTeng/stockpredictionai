"""One active-selection authority: PostgreSQL when configured, files offline.

Manifests in artifact folders are immutable provenance copies. Database mode never
falls back to active.json if the database is unavailable.
"""
from contextlib import contextmanager
from datetime import datetime, date, timezone
import json

from sqlalchemy import select
from database.models import AppSetting, DatasetVersion, ModelRun
from database.session import configured_database_url, create_database_engine, session_factory


@contextmanager
def database():
    url = configured_database_url()
    if not url:
        yield None
        return
    engine = create_database_engine(url)
    try:
        with session_factory(engine).begin() as session:
            if engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session
    finally:
        engine.dispose()


def register_manifest(manifest, directory):
    with database() as session:
        if session is None:
            return
        now = datetime.now(timezone.utc)
        # Dataset digests have a prefix and exceed the legacy id's 64 characters.
        dataset_id = manifest["dataset_version"].removeprefix("dataset-")
        if session.get(DatasetVersion, dataset_id) is None:
            session.add(DatasetVersion(id=dataset_id, name=manifest["symbol"], as_of=date.fromisoformat(manifest["trained_until"]),
                benchmark=manifest["objective"]["benchmark"], horizons=manifest["objective"]["horizons"],
                feature_spec={"names": manifest["features"]}, source_runs=[], checksum=dataset_id, created_at=now))
            session.flush()
        existing = session.get(ModelRun, manifest["run_id"])
        if existing is not None:
            if existing.parameters["manifest"] != manifest:
                raise ValueError("registered model manifest is immutable")
            return
        session.add(ModelRun(id=manifest["run_id"], dataset_version_id=dataset_id,
            model_name="gradient-boosted-excess-return-v1",
            status="validated" if manifest["validation"]["eligible"] else "candidate",
            parameters={"manifest": manifest}, metrics=manifest["validation"],
            artifact_uri=str(directory.resolve()), created_at=now, finished_at=now))
        if session.get(AppSetting, "model_registry_active") is None:
            session.add(AppSetting(key="model_registry_active", value_json="{}", updated_at=now))


def manifest_for(run_id):
    with database() as session:
        if session is None:
            return None
        row = session.get(ModelRun, run_id)
        if row is None:
            raise ValueError("model is not in database registry; import its manifest first")
        return row.parameters["manifest"]


def active_models(root):
    with database() as session:
        if session is None:
            path = root / "active.json"
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        row = session.get(AppSetting, "model_registry_active")
        return json.loads(row.value_json) if row else {}


def select_model(root, symbol, run_id, reason, expected=None):
    from .research import write_json
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    with database() as session:
        if session is None:
            active = active_models(root)
            previous = active.get(symbol)
            if expected is not None and previous != expected:
                raise ValueError("active model changed; reload before updating")
            if run_id:
                active[symbol] = run_id
            else:
                active.pop(symbol, None)
            event = {"at": now.isoformat(), "symbol": symbol, "previous": previous, "run_id": run_id, "reason": reason}
            write_json(root / "activations" / (uuid4().hex + ".json"), event)
            write_json(root / "active.json", active)
            return event
        row = session.scalar(select(AppSetting).where(AppSetting.key == "model_registry_active").with_for_update())
        if row is None:
            raise ValueError("registry not initialized; register a model first")
        active = json.loads(row.value_json)
        previous = active.get(symbol)
        if expected is not None and previous != expected:
            raise ValueError("active model changed; reload before updating")
        if run_id:
            model = session.get(ModelRun, run_id)
            if model is None or model.parameters["manifest"]["symbol"] != symbol or not model.metrics.get("eligible"):
                raise ValueError("model failed registry validation")
            model.status = "active"
            active[symbol] = run_id
        else:
            active.pop(symbol, None)
        if previous and previous != run_id:
            session.get(ModelRun, previous).status = "retired"
        row.value_json, row.updated_at = json.dumps(active), now
        event = {"at": now.isoformat(), "symbol": symbol, "previous": previous, "run_id": run_id, "reason": reason}
        session.add(AppSetting(key="model_activation:" + uuid4().hex, value_json=json.dumps(event), updated_at=now))
        return event


def deactivate_model(root, symbol, expected, reason):
    return select_model(root, symbol, None, reason, expected=expected)
