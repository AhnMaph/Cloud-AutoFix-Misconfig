import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
import time
from urllib.parse import quote, urlparse, urlunparse

import requests


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stdout)

    return result.stdout


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def gitea_base_url() -> str:
    return required_env("GITEA_URL").rstrip("/")


def gitea_owner() -> str:
    return required_env("GITEA_OWNER")


def gitea_token() -> str:
    return required_env("GITEA_TOKEN")


def gitea_headers() -> dict:
    return {
        "Authorization": f"token {gitea_token()}",
        "Content-Type": "application/json",
    }


def provider_suffix(provider: str) -> str:
    if provider == "aws":
        return "aws"
    if provider == "openstack":
        return "openstack"
    raise RuntimeError(f"Unsupported provider: {provider}")


def tenant_repo_name(provider: str, tenant_id: str) -> str:
    """
    Repo format:
      t-alice_aws
      t-alice_openstack
    """
    return f"{tenant_id}_{provider_suffix(provider)}"


def template_repo_name(provider: str) -> str:
    if provider == "aws":
        return required_env("IAC_TEMPLATE_REPO_AWS")
    if provider == "openstack":
        return required_env("IAC_TEMPLATE_REPO_OPENSTACK")
    raise RuntimeError(f"Unsupported provider: {provider}")


def build_clone_url(gitea_url: str, owner: str, repo: str, username: str, token: str) -> str:
    parsed = urlparse(gitea_url.rstrip("/"))

    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError(f"Unsupported GITEA_URL scheme: {parsed.scheme}")

    safe_user = quote(username, safe="")
    safe_token = quote(token, safe="")

    netloc = f"{safe_user}:{safe_token}@{parsed.netloc}"

    base = urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path.rstrip("/"),
            "",
            "",
            "",
        )
    )

    return f"{base}/{owner}/{repo}.git"


def repo_exists(repo: str) -> bool:
    url = f"{gitea_base_url()}/api/v1/repos/{gitea_owner()}/{repo}"

    r = requests.get(
        url,
        headers=gitea_headers(),
        timeout=15,
    )

    if r.status_code == 200:
        return True

    if r.status_code == 404:
        return False

    raise RuntimeError(f"Cannot check repo {repo}: {r.status_code} {r.text}")


def create_private_repo(repo: str):
    url = f"{gitea_base_url()}/api/v1/user/repos"

    payload = {
        "name": repo,
        "private": True,
        "auto_init": False,
        "default_branch": "main",
        "description": f"Tenant IaC repository: {repo}",
    }

    r = requests.post(
        url,
        headers=gitea_headers(),
        json=payload,
        timeout=15,
    )

    if r.status_code not in [200, 201, 409]:
        raise RuntimeError(f"Cannot create repo {repo}: {r.status_code} {r.text}")


def clean_seed_repo(repo_dir: Path):
    """
    Keep pipeline and autofix framework, remove generated/demo state.
    """
    for name in [
        "tenants",
        "fix_output",
        "checkov-results.json",
        "tfsec-results.json",
        "trivy-results.json",
        "opa-response.json",
        "managed_input.json",
        "ingress-payload.json",
        "deploy-meta.json",
        ".terraform",
        ".terraform.lock.hcl",
        "terraform.tfstate",
        "terraform.tfstate.backup",
    ]:
        p = repo_dir / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()

    # Nếu template repo có main.tf demo ở root thì bỏ để tenant repo sạch hơn.
    root_main = repo_dir / "main.tf"
    if root_main.exists():
        root_main.unlink()


def seed_tenant_repo_from_template(provider: str, tenant_repo: str):
    tmp_dir = Path(tempfile.mkdtemp(prefix="iac-seed-"))

    owner = gitea_owner()
    username = required_env("GITEA_USERNAME")
    token = gitea_token()
    base = gitea_base_url()

    template_repo = template_repo_name(provider)

    template_clone = build_clone_url(base, owner, template_repo, username, token)
    tenant_clone = build_clone_url(base, owner, tenant_repo, username, token)

    try:
        run_cmd(["git", "clone", template_clone, "template"], cwd=tmp_dir)

        repo_dir = tmp_dir / "template"

        shutil.rmtree(repo_dir / ".git", ignore_errors=True)
        clean_seed_repo(repo_dir)

        run_cmd(["git", "init"], cwd=repo_dir)
        run_cmd(["git", "checkout", "-b", "main"], cwd=repo_dir)
        run_cmd(["git", "config", "user.name", "Hybrid Cloud Portal Bot"], cwd=repo_dir)
        run_cmd(["git", "config", "user.email", "portal-bot@local.test"], cwd=repo_dir)

        run_cmd(["git", "add", "."], cwd=repo_dir)

        diff_status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(repo_dir),
        )

        if diff_status.returncode == 0:
            (repo_dir / "README.md").write_text(
                f"# {tenant_repo}\n\nTenant IaC repository generated by Hybrid Cloud Portal.\n",
                encoding="utf-8",
            )
            run_cmd(["git", "add", "."], cwd=repo_dir)

        run_cmd(["git", "commit", "-m", "seed tenant iac repository"], cwd=repo_dir)
        run_cmd(["git", "remote", "add", "origin", tenant_clone], cwd=repo_dir)
        run_cmd(["git", "push", "-u", "origin", "main"], cwd=repo_dir)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def ensure_tenant_repo(provider: str, tenant_id: str) -> tuple[str, bool]:
    """
    Return:
      repo_name, repo_was_created
    """
    repo = tenant_repo_name(provider, tenant_id)

    if repo_exists(repo):
        if woodpecker_enabled():
            configure_woodpecker_repo(repo, provider)

        return repo, False

    create_private_repo(repo)
    seed_tenant_repo_from_template(provider, repo)

    if woodpecker_enabled():
        configure_woodpecker_repo(repo, provider)

    return repo, True


def push_iac_request_to_gitea(
    deployment_id: str,
    provider: str,
    tenant_id: str,
    resource_type: str,
    action: str,
    region: str,
    tf_file: Path,
    callback_url: str,
) -> dict:
    owner = gitea_owner()
    username = required_env("GITEA_USERNAME")
    token = gitea_token()
    branch = os.getenv("IAC_TARGET_BRANCH", "main")
    base = gitea_base_url()

    repo, repo_was_created = ensure_tenant_repo(provider, tenant_id)
    woodpecker_info = None

    if woodpecker_enabled():
        woodpecker_info = configure_woodpecker_repo(repo, provider)

    clone_url = build_clone_url(
        gitea_url=base,
        owner=owner,
        repo=repo,
        username=username,
        token=token,
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="iac-push-"))

    try:
        run_cmd(
            ["git", "clone", "--branch", branch, clone_url, "repo"],
            cwd=tmp_dir,
        )

        repo_dir = tmp_dir / "repo"

        run_cmd(["git", "config", "user.name", "Hybrid Cloud Portal Bot"], cwd=repo_dir)
        run_cmd(["git", "config", "user.email", "portal-bot@local.test"], cwd=repo_dir)

        tf_workdir = Path(resource_type)
        target_dir = repo_dir / tf_workdir
        target_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(tf_file, target_dir / "main.tf")

        deploy_meta = {
            "deployment_id": deployment_id,
            "tenant_id": tenant_id,
            "provider": provider,
            "resource_type": resource_type,
            "action": action,
            "region": region,
            "tf_workdir": str(tf_workdir),
            "callback_url": callback_url,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

        # Root file: Woodpecker reads this quickly.
        (repo_dir / "deploy-meta.json").write_text(
            json.dumps(deploy_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Copy inside resource folder: audit/history.
        (target_dir / "deploy-meta.json").write_text(
            json.dumps(deploy_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        run_cmd(["git", "add", "."], cwd=repo_dir)

        diff_status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(repo_dir),
        )

        if diff_status.returncode == 0:
            commit_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_dir).strip()

            return {
                "repo": f"{owner}/{repo}",
                "branch": branch,
                "commit": commit_sha,
                "changed": False,
                "tf_workdir": str(tf_workdir),
                "gitea_url": f"{base}/{owner}/{repo}",
                "message": "No IaC change to push",
            }

        commit_msg = f"{deployment_id} {provider}/{tenant_id}/{resource_type} {action}"

        run_cmd(["git", "commit", "-m", commit_msg], cwd=repo_dir)
        run_cmd(["git", "push", "origin", branch], cwd=repo_dir)

        commit_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_dir).strip()

        trigger_commit = None

        if repo_was_created and woodpecker_enabled():
            trigger_commit = trigger_woodpecker_pipeline(repo)

        return {
            "repo": f"{owner}/{repo}",
            "branch": branch,
            "commit": commit_sha,
            "trigger_commit": trigger_commit,
            "changed": True,
            "tf_workdir": str(tf_workdir),
            "gitea_url": f"{base}/{owner}/{repo}",
            "woodpecker": woodpecker_info,
            "message": "IaC template pushed to tenant private repository",
        }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def woodpecker_enabled() -> bool:
    return os.getenv("AUTO_ENABLE_WOODPECKER", "true").lower() in {"1", "true", "yes", "on"}


def woodpecker_url() -> str:
    return os.getenv("WOODPECKER_URL", "").rstrip("/")


def woodpecker_token() -> str:
    return os.getenv("WOODPECKER_TOKEN", "")


def woodpecker_headers() -> dict:
    token = woodpecker_token()
    if not token:
        raise RuntimeError("Missing WOODPECKER_TOKEN")

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_gitea_repo_info(repo: str) -> dict:
    url = f"{gitea_base_url()}/api/v1/repos/{gitea_owner()}/{repo}"

    r = requests.get(
        url,
        headers=gitea_headers(),
        timeout=15,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Cannot get Gitea repo info {repo}: {r.status_code} {r.text}")

    return r.json()


def activate_woodpecker_repo(repo: str) -> dict | None:
    """
    Enable repository in Woodpecker immediately after creating it in Gitea.
    Woodpecker needs forge_remote_id = Gitea repo id.
    """
    if not woodpecker_enabled():
        return None

    if not woodpecker_url():
        raise RuntimeError("Missing WOODPECKER_URL")

    repo_info = get_gitea_repo_info(repo)
    forge_remote_id = str(repo_info["id"])

    url = f"{woodpecker_url()}/api/repos"

    r = requests.post(
        url,
        headers=woodpecker_headers(),
        params={"forge_remote_id": forge_remote_id},
        timeout=20,
    )

    if r.status_code not in [200, 201, 409]:
        raise RuntimeError(
            f"Cannot activate Woodpecker repo {repo}: {r.status_code} {r.text}"
        )

    if not r.text:
        return None

    try:
        return r.json()
    except Exception:
        return None


def lookup_woodpecker_repo(repo_full_name: str) -> dict:
    """
    Lookup activated Woodpecker repo by full name, for example:
      gitea-admin/t-hehehehe_aws
    """
    import urllib.parse

    encoded = urllib.parse.quote(repo_full_name, safe="")
    url = f"{woodpecker_url()}/api/repos/lookup/{encoded}"

    r = requests.get(
        url,
        headers=woodpecker_headers(),
        timeout=20,
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"Cannot lookup Woodpecker repo {repo_full_name}: {r.status_code} {r.text}"
        )

    return r.json()


def upsert_woodpecker_secret(repo_id: int, name: str, value: str):
    """
    Create or update a Woodpecker repository secret.
    Idempotent: chạy nhiều lần không bị lỗi duplicate.
    """
    if not value:
        return

    from urllib.parse import quote

    secret_name = quote(name, safe="")
    base = f"{woodpecker_url()}/api/repos/{repo_id}/secrets"
    secret_url = f"{base}/{secret_name}"

    payload = {
        "name": name,
        "value": value,
        "events": ["push", "pull_request"],
        "images": [],
    }

    # 1. Kiểm tra secret đã tồn tại chưa
    get_res = requests.get(
        secret_url,
        headers=woodpecker_headers(),
        timeout=20,
    )

    # 2. Nếu đã tồn tại thì update bằng PATCH
    if get_res.status_code == 200:
        patch_res = requests.patch(
            secret_url,
            headers=woodpecker_headers(),
            json=payload,
            timeout=20,
        )

        if patch_res.status_code in [200, 204]:
            return

        raise RuntimeError(
            f"Cannot update Woodpecker secret {name}: "
            f"{patch_res.status_code} {patch_res.text}"
        )

    # 3. Nếu chưa tồn tại thì tạo mới
    if get_res.status_code == 404:
        post_res = requests.post(
            base,
            headers=woodpecker_headers(),
            json=payload,
            timeout=20,
        )

        if post_res.status_code in [200, 201]:
            return

        # Một số bản Woodpecker trả 500 khi duplicate thay vì 409.
        # Nếu gặp duplicate thì thử PATCH lại.
        if "duplicate" in post_res.text.lower() or "constraints" in post_res.text.lower():
            patch_res = requests.patch(
                secret_url,
                headers=woodpecker_headers(),
                json=payload,
                timeout=20,
            )

            if patch_res.status_code in [200, 204]:
                return

            raise RuntimeError(
                f"Secret {name} exists but cannot update: "
                f"{patch_res.status_code} {patch_res.text}"
            )

        raise RuntimeError(
            f"Cannot create Woodpecker secret {name}: "
            f"{post_res.status_code} {post_res.text}"
        )

    raise RuntimeError(
        f"Cannot check Woodpecker secret {name}: "
        f"{get_res.status_code} {get_res.text}"
    )


def configure_woodpecker_repo(repo: str, provider: str) -> dict | None:
    """
    Activate repo and add required secrets.
    """
    if not woodpecker_enabled():
        return None

    activate_woodpecker_repo(repo)

    full_name = f"{gitea_owner()}/{repo}"
    wp_repo = lookup_woodpecker_repo(full_name)
    repo_id = wp_repo["id"]
    
    repair_woodpecker_repo(repo_id)

    # Common secrets for all tenant repos.
    upsert_woodpecker_secret(repo_id, "GITEA_URL", "http://gitea:3000")
    upsert_woodpecker_secret(repo_id, "GITEA_TOKEN", gitea_token())
    upsert_woodpecker_secret(repo_id, "INGRESS_CALLBACK_TOKEN", os.getenv("CI_CALLBACK_TOKEN", ""))

    # Provider-specific secrets.
    if provider == "aws":
        for name in [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_DEFAULT_REGION",
        ]:
            upsert_woodpecker_secret(repo_id, name, os.getenv(name, ""))

    if provider == "openstack":
        for name in [
            "OS_AUTH_URL",
            "OS_USERNAME",
            "OS_PASSWORD",
            "OS_USER_DOMAIN_NAME",
            "OS_PROJECT_NAME",
            "OS_PROJECT_DOMAIN_NAME",
            "OS_REGION_NAME",
            "OS_INTERFACE",
            "OS_IDENTITY_API_VERSION",
        ]:
            upsert_woodpecker_secret(repo_id, name, os.getenv(name, ""))

    return {
        "woodpecker_repo_id": repo_id,
        "woodpecker_repo": full_name,
        "woodpecker_enabled": True,
    }

def repair_woodpecker_repo(repo_id: int):
    if not woodpecker_enabled():
        return

    url = f"{woodpecker_url()}/api/repos/{repo_id}/repair"

    r = requests.post(
        url,
        headers=woodpecker_headers(),
        timeout=20,
    )

    if r.status_code not in [200, 204]:
        raise RuntimeError(
            f"Cannot repair Woodpecker repo {repo_id}: {r.status_code} {r.text}"
        )
        
def trigger_woodpecker_pipeline(repo: str) -> str:
    """
    Push an empty commit after Woodpecker repo is enabled/repaired.
    This guarantees Gitea emits a fresh push webhook.
    """
    owner = gitea_owner()
    username = required_env("GITEA_USERNAME")
    token = gitea_token()
    base = gitea_base_url()
    branch = os.getenv("IAC_TARGET_BRANCH", "main")

    clone_url = build_clone_url(base, owner, repo, username, token)
    tmp_dir = Path(tempfile.mkdtemp(prefix="iac-trigger-"))

    try:
        run_cmd(["git", "clone", "--branch", branch, clone_url, "repo"], cwd=tmp_dir)

        repo_dir = tmp_dir / "repo"

        run_cmd(["git", "config", "user.name", "Hybrid Cloud Portal Bot"], cwd=repo_dir)
        run_cmd(["git", "config", "user.email", "portal-bot@local.test"], cwd=repo_dir)

        run_cmd(
            ["git", "commit", "--allow-empty", "-m", "trigger woodpecker pipeline after enable"],
            cwd=repo_dir,
        )

        run_cmd(["git", "push", "origin", branch], cwd=repo_dir)

        return run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_dir).strip()

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)