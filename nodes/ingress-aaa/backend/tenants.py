import json
import os
import time
from pathlib import Path
from typing import Any


TENANT_REGISTRY_PATH = Path(
    os.getenv("TENANT_REGISTRY_PATH", "/app/data/tenants.json")
)


def _ensure_registry_file():
    TENANT_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not TENANT_REGISTRY_PATH.exists():
        TENANT_REGISTRY_PATH.write_text("{}", encoding="utf-8")


def _load_registry() -> dict[str, Any]:
    _ensure_registry_file()

    try:
        return json.loads(TENANT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_registry(data: dict[str, Any]):
    _ensure_registry_file()
    TENANT_REGISTRY_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_tenant_record(
    tenant_id: str,
    username: str,
    email: str | None = None,
) -> dict[str, Any]:
    """
    Tạo tenant record local.

    Đây là nơi lưu mapping:
    - tenant_id
    - user owner
    - AWS role ARN
    - OpenStack project
    - trạng thái provisioning
    """
    data = _load_registry()

    if tenant_id in data:
        return data[tenant_id]

    now = int(time.time())

    record = {
        "tenant_id": tenant_id,
        "owner_username": username,
        "owner_email": email,
        "status": "created",

        "aws": {
            "role_name": None,
            "role_arn": None,
            "provisioned": False,
            "last_error": None,
        },

        "openstack": {
            "project_name": tenant_id,
            "project_id": None,
            "provisioned": False,
            "last_error": None,
        },

        "created_at": now,
        "updated_at": now,
    }

    data[tenant_id] = record
    _save_registry(data)

    return record


def get_tenant_record(tenant_id: str) -> dict[str, Any] | None:
    data = _load_registry()
    return data.get(tenant_id)


def update_tenant_record(tenant_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = _load_registry()

    if tenant_id not in data:
        raise KeyError(f"Tenant not found: {tenant_id}")

    record = data[tenant_id]

    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            record[key].update(value)
        else:
            record[key] = value

    record["updated_at"] = int(time.time())

    data[tenant_id] = record
    _save_registry(data)

    return record


def list_tenant_records() -> list[dict[str, Any]]:
    data = _load_registry()
    return list(data.values())