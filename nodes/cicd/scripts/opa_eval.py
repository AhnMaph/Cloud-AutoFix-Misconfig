#!/usr/bin/env python3
"""
opa_eval.py — Merge scan results từ Checkov/tfsec/Trivy rồi POST lên OPA
Chạy trong Woodpecker pipeline step "opa-evaluate"
"""

import json
import os
import sys
import datetime
import requests

OPA_URL       = os.getenv("OPA_URL", "http://172.20.0.13:8181")
ELK_URL       = os.getenv("ELK_LOGSTASH_URL", "http://192.168.10.13:5055")
WORKSPACE     = "/workspace"
OPA_POLICY    = "aws/iac/deny"   # package aws.iac → deny


def load_json(path: str) -> dict:
    """Load JSON file, trả về dict rỗng nếu không tồn tại hoặc lỗi."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  WARN: cannot load {path}: {e}")
        return {}


def main():
    print("=" * 55)
    print("OPA Evaluator — merging scan results")
    print("=" * 55)

    checkov = load_json(f"{WORKSPACE}/checkov-results.json")
    tfsec   = load_json(f"{WORKSPACE}/tfsec-results.json")
    trivy   = load_json(f"{WORKSPACE}/trivy-results.json")

    # Payload gửi lên OPA — cấu trúc phải khớp với input trong .rego
    payload = {
        "input": {
            "checkov_results": checkov,
            "tfsec_results":   tfsec,
            "trivy_results":   trivy,
            "metadata": {
                "timestamp":  datetime.datetime.utcnow().isoformat() + "Z",
                "commit_sha": os.getenv("CI_COMMIT_SHA", "unknown"),
                "repo_name":  os.getenv("CI_REPO", "unknown"),
                "pipeline_id": os.getenv("CI_PIPELINE_NUMBER", "0"),
            }
        }
    }

    # ── POST lên OPA ──────────────────────────────────────
    print(f"\n[1] Evaluating policy: {OPA_URL}/v1/data/{OPA_POLICY}")
    try:
        resp = requests.post(
            f"{OPA_URL}/v1/data/{OPA_POLICY}",
            json=payload,
            timeout=15
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERROR: Cannot reach OPA: {e}")
        print("  FAIL — OPA unreachable, blocking pipeline as precaution")
        sys.exit(1)

    result = resp.json()
    deny_msgs = result.get("result", [])

    # ── Lấy summary ──────────────────────────────────────
    try:
        summary_resp = requests.post(
            f"{OPA_URL}/v1/data/aws/iac/summary",
            json=payload, timeout=15
        )
        summary = summary_resp.json().get("result", {})
    except Exception:
        summary = {}

    # ── In kết quả ───────────────────────────────────────
    print(f"\n[2] OPA result:")
    if deny_msgs:
        print(f"  DENIED ({len(deny_msgs)} finding(s)):")
        for msg in deny_msgs:
            print(f"    - {msg}")
    else:
        print("  PASSED — no CRITICAL/HIGH findings")

    if summary:
        print(f"\n[3] Summary: {json.dumps(summary, indent=4)}")

    # ── Gửi audit log sang ELK ───────────────────────────
    elk_payload = {
        "@timestamp": payload["input"]["metadata"]["timestamp"],
        "pipeline":   "iac-scan",
        "commit_sha": payload["input"]["metadata"]["commit_sha"],
        "repo":       payload["input"]["metadata"]["repo_name"],
        "pipeline_id": payload["input"]["metadata"]["pipeline_id"],
        "opa_denied": len(deny_msgs),
        "opa_passed": len(deny_msgs) == 0,
        "deny_messages": deny_msgs,
        "summary":    summary,
    }
    try:
        elk_resp = requests.post(ELK_URL, json=elk_payload, timeout=10)
        print(f"\n[4] ELK ingest: HTTP {elk_resp.status_code}")
    except requests.RequestException as e:
        print(f"\n[4] WARN: ELK unreachable ({e}) — continuing anyway")

    # ── Exit code quyết định pipeline pass/fail ──────────
    if deny_msgs:
        print("\nPIPELINE: FAILED — fix findings above before deploy")
        sys.exit(1)
    else:
        print("\nPIPELINE: PASSED — proceeding to deploy")
        sys.exit(0)


if __name__ == "__main__":
    main()
