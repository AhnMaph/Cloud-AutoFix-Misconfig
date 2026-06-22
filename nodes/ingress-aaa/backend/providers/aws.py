import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal
import boto3
from botocore.exceptions import ClientError


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

def get_tenant_role_name(tenant_id: str) -> str:
    tenant_slug = safe_slug(tenant_id)
    return f"hybridcompany-{tenant_slug}-deploy-role"


def get_tenant_role_arn(tenant_id: str, aws_account_id: str) -> str:
    role_name = get_tenant_role_name(tenant_id)
    return f"arn:aws:iam::{aws_account_id}:role/{role_name}"


def create_tenant_iam_role(tenant_id: str, aws_account_id: str) -> dict:
    """
    Tạo IAM Role riêng cho tenant.
    Role này dùng để Terraform deploy AWS resource cho đúng tenant.
    """
    tenant_slug = safe_slug(tenant_id)
    role_name = get_tenant_role_name(tenant_slug)
    role_arn = get_tenant_role_arn(tenant_slug, aws_account_id)

    iam = boto3.client("iam")

    vault_broker_user = os.getenv("VAULT_BROKER_AWS_USER", "vault-aws-broker")
    vault_broker_arn = os.getenv(
        "VAULT_BROKER_AWS_PRINCIPAL_ARN",
        f"arn:aws:iam::{aws_account_id}:user/{vault_broker_user}",
    )

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TrustVaultBrokerUser",
                "Effect": "Allow",
                "Principal": {
                    "AWS": vault_broker_arn
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }

    bucket_prefix = f"{PROJECT_NAME}-{tenant_slug}-"

    permission_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TenantS3BucketAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:CreateBucket",
                    "s3:DeleteBucket",
                    "s3:ListBucket",

                    # Terraform AWS provider thường read nhiều bucket subresources
                    "s3:GetBucket*",
                    "s3:Get*Configuration",
                    "s3:GetReplicationConfiguration",

                    # Các quyền write config mà template đang quản lý
                    "s3:PutBucket*",
                    "s3:PutBucketAcl",
                    "s3:GetBucketAcl",
                    "s3:DeleteBucket*",
                    "s3:GetBucketLogging",
                    "s3:PutBucketLogging",
                    "s3:Put*Configuration",
                    "s3:Delete*Configuration"
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket_prefix}*"
                ]
            },
            {
                "Sid": "TenantS3ObjectAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts"
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket_prefix}*/*"
                ]
            },
            {
                "Sid": "TenantKmsForS3",
                "Effect": "Allow",
                "Action": [
                    "kms:CreateKey",
                    "kms:CreateAlias",
                    "kms:UpdateAlias",
                    "kms:DeleteAlias",
                    "kms:DescribeKey",
                    "kms:GetKeyPolicy",
                    "kms:PutKeyPolicy",
                    "kms:EnableKeyRotation",
                    "kms:GetKeyRotationStatus",
                    "kms:ScheduleKeyDeletion",
                    "kms:CancelKeyDeletion",
                    "kms:TagResource",
                    "kms:UntagResource",
                    "kms:ListResourceTags",
		    "kms:ListAliases",
		    "kms:ListKeys",
                    "kms:ListAliases"
                ],
                "Resource": "*"
            }
        ]
    }

    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"Deploy role for tenant {tenant_slug}",
            Tags=[
                {"Key": "Tenant", "Value": tenant_slug},
                {"Key": "ManagedBy", "Value": "hybrid-cloud-portal"}
            ],
        )
    except iam.exceptions.EntityAlreadyExistsException:
        pass

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=f"{tenant_slug}-deploy-policy",
        PolicyDocument=json.dumps(permission_policy),
    )

    return {
        "role_name": role_name,
        "role_arn": role_arn,
    }


def assume_tenant_role(tenant_id: str, aws_account_id: str) -> dict:
    """
    Backend dùng bootstrap credential hiện tại để AssumeRole sang tenant role.
    Terraform sẽ dùng temporary credentials này.
    """
    tenant_slug = safe_slug(tenant_id)
    role_arn = get_tenant_role_arn(tenant_slug, aws_account_id)

    sts = boto3.client("sts")

    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"deploy-{tenant_slug}",
        DurationSeconds=3600,
    )

    creds = response["Credentials"]

    return {
        "AWS_ACCESS_KEY_ID": creds["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": creds["SecretAccessKey"],
        "AWS_SESSION_TOKEN": creds["SessionToken"],
    }

def run_cmd(
    cmd: list[str],
    cwd: Path,
    timeout: int = 300,
    env_overrides: dict | None = None,
) -> str:
    env = os.environ.copy()

    if env_overrides:
        env.update(env_overrides)

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
    
    aws_account_id = os.getenv("AWS_ACCOUNT_ID")
    if not aws_account_id:
        raise RuntimeError("Missing AWS_ACCOUNT_ID")

    aws_env = assume_tenant_role(tenant_slug, aws_account_id)
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
        env_overrides=aws_env,
    )

    validate_output = run_cmd(
        ["terraform", "validate"],
        cwd=workdir,
        timeout=120,
        env_overrides=aws_env,
    )

    if action == "plan":
        deploy_output = run_cmd(
            ["terraform", "plan", "-input=false", *tfvars],
            cwd=workdir,
            timeout=300,
            env_overrides=aws_env,
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
            env_overrides=aws_env,
        )

        output_json_raw = run_cmd(
            ["terraform", "output", "-json"],
            cwd=workdir,
            timeout=120,
            env_overrides=aws_env,
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
            env_overrides=aws_env,
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
