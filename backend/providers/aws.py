import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal


TF_TEMPLATE_DIR = Path(
    os.getenv(
        "AWS_TF_TEMPLATE_DIR",
        "/app/terraform/aws/s3_private_bucket"
    )
)

TF_STATE_ROOT = Path(
    os.getenv(
        "TERRAFORM_STATE_ROOT",
        "/app/tfstate"
    )
)

PROJECT_NAME = os.getenv("AWS_PROJECT_NAME", "hybrid-portal")


def safe_slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")

    if not value:
        raise ValueError("Invalid tenant_id")

    return value[:40]


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 300) -> str:
    env = os.environ.copy()

    process = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )

    if process.returncode != 0:
        raise RuntimeError(process.stdout)

    return process.stdout


def prepare_workspace(tenant_id: str) -> Path:
    tenant_slug = safe_slug(tenant_id)
    workdir = TF_STATE_ROOT / "aws" / tenant_slug

    workdir.mkdir(parents=True, exist_ok=True)

    if not TF_TEMPLATE_DIR.exists():
        raise RuntimeError(f"Terraform template not found: {TF_TEMPLATE_DIR}")

    shutil.copytree(
        TF_TEMPLATE_DIR,
        workdir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".terraform", ".terraform.lock.hcl"),
    )

    return workdir


def terraform_aws_deploy(
    tenant_id: str,
    aws_region: str,
    action: Literal["plan", "apply", "destroy"] = "plan",
    workdir: Path | None = None,   # ← thêm dòng này
) -> dict:
    tenant_slug = safe_slug(tenant_id)
    # Nếu workdir được truyền vào thì dùng luôn, không copy template nữa
    if workdir is None:
        workdir = prepare_workspace(tenant_slug)

    tfvars = [
        f"-var=tenant_id={tenant_slug}",
        f"-var=aws_region={aws_region}",
        f"-var=project_name={PROJECT_NAME}",
    ]

    init_output = run_cmd(
        ["terraform", "init", "-input=false"],
        cwd=workdir,
        timeout=300,
    )

    validate_output = run_cmd(
        ["terraform", "validate"],
        cwd=workdir,
        timeout=120,
    )

    if action == "plan":
        deploy_output = run_cmd(
            ["terraform", "plan", "-input=false", *tfvars],
            cwd=workdir,
            timeout=300,
        )

        return {
            "status": "planned",
            "provider": "aws",
            "tenant_id": tenant_slug,
            "region": aws_region,
            "terraform_init": tail(init_output),
            "terraform_validate": tail(validate_output),
            "terraform_output": tail(deploy_output, 120),
        }

    if action == "apply":
        deploy_output = run_cmd(
            ["terraform", "apply", "-input=false", "-auto-approve", *tfvars],
            cwd=workdir,
            timeout=600,
        )

        output_json_raw = run_cmd(
            ["terraform", "output", "-json"],
            cwd=workdir,
            timeout=120,
        )

        try:
            output_json = json.loads(output_json_raw)
        except json.JSONDecodeError:
            output_json = {}

        return {
            "status": "applied",
            "provider": "aws",
            "tenant_id": tenant_slug,
            "region": aws_region,
            "outputs": output_json,
            "terraform_output": tail(deploy_output, 120),
        }

    if action == "destroy":
        deploy_output = run_cmd(
            ["terraform", "destroy", "-input=false", "-auto-approve", *tfvars],
            cwd=workdir,
            timeout=600,
        )

        return {
            "status": "destroyed",
            "provider": "aws",
            "tenant_id": tenant_slug,
            "region": aws_region,
            "terraform_output": tail(deploy_output, 120),
        }

    raise ValueError(f"Unsupported action: {action}")


def tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.splitlines()[-lines:])