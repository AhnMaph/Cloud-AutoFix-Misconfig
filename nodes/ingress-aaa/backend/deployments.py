import json
import os
import time
from pathlib import Path
from typing import Any


DEPLOYMENT_STORE_PATH = Path(
    os.getenv("DEPLOYMENT_STORE_PATH", "/app/data/deployments.json")
)


def _ensure_file():
    DEPLOYMENT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not DEPLOYMENT_STORE_PATH.exists():
        DEPLOYMENT_STORE_PATH.write_text("{}", encoding="utf-8")


def _load() -> dict[str, Any]:
    _ensure_file()

    try:
        return json.loads(DEPLOYMENT_STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data: dict[str, Any]):
    _ensure_file()
    DEPLOYMENT_STORE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_deployment(record: dict[str, Any]) -> dict[str, Any]:
    data = _load()
    deployment_id = record["deployment_id"]

    now = int(time.time())

    record.setdefault("created_at", now)
    record.setdefault("updated_at", now)

    data[deployment_id] = record
    _save(data)

    return record


def update_deployment(deployment_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = _load()

    if deployment_id not in data:
        raise KeyError(f"Deployment not found: {deployment_id}")

    record = data[deployment_id]

    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            record[key].update(value)
        else:
            record[key] = value

    record["updated_at"] = int(time.time())

    data[deployment_id] = record
    _save(data)

    return record


def get_deployment(deployment_id: str) -> dict[str, Any] | None:
    return _load().get(deployment_id)


def list_deployments_by_tenant(tenant_id: str) -> list[dict[str, Any]]:
    data = _load()

    items = [
        item
        for item in data.values()
        if item.get("tenant_id") == tenant_id
    ]

    return sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)
