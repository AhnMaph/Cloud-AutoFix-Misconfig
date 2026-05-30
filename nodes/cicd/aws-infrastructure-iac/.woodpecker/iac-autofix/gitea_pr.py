#!/usr/bin/env python3
"""
gitea_pr.py — Auto-PR creator for IaC Auto-Fix pipeline

Flow:
  1. Đọc fix_report.json từ autofix step
  2. Nếu không có file nào được fix → exit 0 (skip)
  3. Copy các file đã fix vào working tree (overwrite originals)
  4. git checkout -b autofix/<timestamp>
  5. git add + git commit
  6. git push lên Gitea (HTTP + PAT)
  7. Gọi Gitea API tạo PR, gắn label "autofix" + body = PR_SUMMARY.md
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Config từ env (inject qua Woodpecker secrets)
# ─────────────────────────────────────────────────────────────────────────────

def require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"[!] Missing required env var: {key}", file=sys.stderr)
        sys.exit(1)
    return val


# ─────────────────────────────────────────────────────────────────────────────
# Git helpers (subprocess, không dùng lib nặng)
# ─────────────────────────────────────────────────────────────────────────────

def git(*args: str, check: bool = True, capture: bool = False) -> str:
    cmd = ["git", *args]
    result = subprocess.run(
        cmd, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    return (result.stdout or "").strip()


def git_current_branch() -> str:
    # CI thường checkout detached HEAD — fallback ke CI env vars
    branch = git("rev-parse", "--abbrev-ref", "HEAD", capture=True)
    if branch == "HEAD":
        # Woodpecker sets CI_COMMIT_BRANCH
        branch = os.environ.get("CI_COMMIT_BRANCH", "main")
    return branch


def git_configure(author_name: str, author_email: str):
    git("config", "user.name",  author_name)
    git("config", "user.email", author_email)


def git_remote_with_token(gitea_url: str, owner: str, repo: str, token: str) -> str:
    """Build authenticated remote URL: https://<token>@<host>/<owner>/<repo>.git"""
    # Strip trailing slash and scheme
    host = gitea_url.rstrip("/")
    if "://" in host:
        scheme, rest = host.split("://", 1)
    else:
        scheme, rest = "https", host
    return f"{scheme}://oauth2:{token}@{rest}/{owner}/{repo}.git"


# ─────────────────────────────────────────────────────────────────────────────
# Gitea REST API
# ─────────────────────────────────────────────────────────────────────────────

class GiteaAPI:
    def __init__(self, base_url: str, token: str, owner: str, repo: str):
        self.base    = base_url.rstrip("/")
        self.token   = token
        self.owner   = owner
        self.repo    = repo
        self.headers = {
            "Authorization": f"token {token}",
            "Content-Type" : "application/json",
            "Accept"       : "application/json",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url  = f"{self.base}/api/v1{path}"
        data = json.dumps(body).encode() if body else None
        req  = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            print(f"[!] Gitea API {method} {path} → HTTP {e.code}: {msg}", file=sys.stderr)
            raise

    def ensure_label(self, name: str, color: str = "#0075ca") -> int:
        """Get or create a label, return its ID."""
        labels = self._request("GET", f"/repos/{self.owner}/{self.repo}/labels")
        for lbl in labels:
            if lbl["name"] == name:
                return lbl["id"]
        new_lbl = self._request("POST", f"/repos/{self.owner}/{self.repo}/labels",
                                 {"name": name, "color": color})
        return new_lbl["id"]

    def create_pr(self, title: str, head: str, base: str,
                  body: str, label_ids: list[int]) -> dict:
        return self._request("POST", f"/repos/{self.owner}/{self.repo}/pulls", {
            "title"     : title,
            "head"      : head,
            "base"      : base,
            "body"      : body,
            "labels"    : label_ids,
        })

    def add_pr_comment(self, pr_number: int, body: str) -> dict:
        return self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/issues/{pr_number}/comments",
            {"body": body},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create Gitea PR from IaC auto-fix output")
    parser.add_argument("--fix-dir",     default="fix_output",
                        help="Directory with patched .tf files (default: fix_output)")
    parser.add_argument("--report-json", default="fix_output/fix_report.json",
                        help="fix_report.json from autofix step")
    parser.add_argument("--report-md",   default="fix_output/PR_SUMMARY.md",
                        help="PR_SUMMARY.md for PR body")
    parser.add_argument("--base-branch", default=None,
                        help="Target branch for PR (default: current branch)")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Git ops only, skip Gitea API call")
    args = parser.parse_args()

    # ── Read env ──────────────────────────────────────────────────────────────
    gitea_url   = require_env("GITEA_URL")          # e.g. http://192.168.154.129:3000
    gitea_token = require_env("GITEA_TOKEN")        # PAT
    repo_owner  = require_env("CI_REPO_OWNER")      # set by Woodpecker automatically
    repo_name   = require_env("CI_REPO_NAME")       # set by Woodpecker automatically
    git_email   = os.environ.get("GIT_AUTHOR_EMAIL", "autofix-bot@ci.local")
    git_name    = os.environ.get("GIT_AUTHOR_NAME",  "IaC AutoFix Bot")

    fix_dir     = Path(args.fix_dir)
    report_json = Path(args.report_json)
    report_md   = Path(args.report_md)

    # ── Load report ───────────────────────────────────────────────────────────
    if not report_json.exists():
        print("[!] fix_report.json not found — autofix may not have run.", file=sys.stderr)
        sys.exit(1)

    report = json.loads(report_json.read_text())
    summary = report.get("summary", {})

    fixed_count = summary.get("fixed", 0)
    if fixed_count == 0:
        print("[✓] No fixes applied — skipping PR creation.")
        sys.exit(0)

    patched_files: dict[str, str] = report.get("patched_files", {})
    if not patched_files:
        print("[✓] patched_files is empty — nothing to commit.")
        sys.exit(0)

    print(f"\n[*] {fixed_count} fix(es) found across {len(patched_files)} file(s).")

    # ── Determine branch names ────────────────────────────────────────────────
    base_branch = args.base_branch or git_current_branch()
    timestamp   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fix_branch  = f"autofix/{timestamp}"

    print(f"[*] Base branch : {base_branch}")
    print(f"[*] Fix branch  : {fix_branch}")

    # ── Copy patched files into working tree ──────────────────────────────────
    # patched_files = {"/abs/original/path": "fix_output/relative/path"}
    copied = []
    for original_abs, fixed_rel in patched_files.items():
        src = Path(fixed_rel)            # fix_output/ec2.tf
        dst = Path(original_abs)         # original location in repo
        if not src.exists():
            # Try relative to fix_dir
            src = fix_dir / Path(original_abs).name
        if not src.exists():
            print(f"  [!] Cannot find patched file for {original_abs} — skipping")
            continue
        shutil.copy2(src, dst)
        copied.append(str(dst))
        print(f"  [+] Copied {src} → {dst}")

    if not copied:
        print("[!] No files could be copied into working tree.", file=sys.stderr)
        sys.exit(1)

    # ── Git: configure + branch + commit ─────────────────────────────────────
    git_configure(git_name, git_email)
    git("checkout", "-b", fix_branch)

    # Stage only the patched tf files + the reports
    for f in copied:
        git("add", f)
    if report_md.exists():
        git("add", str(report_md))
    if report_json.exists():
        git("add", str(report_json))

    # Check if there is actually something staged
    diff_stat = git("diff", "--cached", "--stat", capture=True)
    if not diff_stat:
        print("[✓] Nothing staged — all fixes already committed or files unchanged.")
        sys.exit(0)

    commit_msg = (
        f"fix(iac-autofix): auto-remediate {fixed_count} LOW/MEDIUM misconfig(s)\n\n"
        f"Fixed by IaC Auto-Fix pipeline on {timestamp}.\n"
        f"Files patched: {', '.join(Path(p).name for p in copied)}\n\n"
        f"[skip ci]"   # prevent recursive pipeline trigger
    )
    git("commit", "-m", commit_msg)
    print(f"[+] Committed on branch: {fix_branch}")

    # ── Git push ──────────────────────────────────────────────────────────────
    remote_url = git_remote_with_token(gitea_url, repo_owner, repo_name, gitea_token)
    git("remote", "set-url", "origin", remote_url)
    git("push", "origin", fix_branch)
    print(f"[+] Pushed branch: {fix_branch}")

    if args.dry_run:
        print("[!] Dry-run: skipping Gitea PR API call.")
        sys.exit(0)

    # ── Gitea API: create PR ──────────────────────────────────────────────────
    api = GiteaAPI(gitea_url, gitea_token, repo_owner, repo_name)

    # PR body = PR_SUMMARY.md content (Gitea renders Markdown)
    pr_body = report_md.read_text(encoding="utf-8") if report_md.exists() else \
        f"Auto-fix: {fixed_count} LOW/MEDIUM misconfig(s) patched."

    # Truncate if too long (Gitea has ~65536 char limit)
    if len(pr_body) > 60000:
        pr_body = pr_body[:60000] + "\n\n_[truncated — see fix_report.json for full details]_"

    # Ensure labels exist
    label_id_autofix  = api.ensure_label("autofix",         "#0075ca")
    label_id_security = api.ensure_label("security",        "#e4e669")
    label_id_bot      = api.ensure_label("bot",             "#cfd3d7")

    pr_title = f"[AutoFix] Remediate {fixed_count} IaC misconfig(s) — {timestamp}"

    try:
        pr = api.create_pr(
            title     = pr_title,
            head      = fix_branch,
            base      = base_branch,
            body      = pr_body,
            label_ids = [label_id_autofix, label_id_security, label_id_bot],
        )
        pr_url    = pr.get("html_url", "")
        pr_number = pr.get("number", "?")
        print(f"\n{'='*60}")
        print(f"  ✅ PR created successfully!")
        print(f"  PR #{pr_number}: {pr_title}")
        print(f"  URL: {pr_url}")
        print(f"{'='*60}\n")

    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("[!] PR already exists for this branch.")
        else:
            print(f"[!] Failed to create PR: HTTP {e.code}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
