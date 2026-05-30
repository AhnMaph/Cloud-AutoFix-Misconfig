# IaC Auto-Fix Framework

Auto-fix LOW/MEDIUM severity misconfigs từ **Checkov + tfsec + Trivy** trên `main.tf`,
kèm sinh PR summary report (Markdown + HTML).

## Cấu trúc

```
iac-autofix/
├── autofix.py                  # Orchestrator chính
├── normalizers/
│   ├── checkov_normalizer.py   # Normalize Checkov JSON → common schema
│   ├── tfsec_normalizer.py     # Normalize tfsec JSON
│   └── trivy_normalizer.py     # Normalize Trivy JSON
├── patchers/
│   └── tf_patcher.py           # Rule registry + TF file patcher
├── reports/
│   └── report_generator.py     # Sinh PR_SUMMARY.md + HTML
└── tests/
    ├── main.tf                 # Sample vulnerable TF file
    ├── sample_scan_output.json # Sample merged scan JSON
    └── run_test.py             # Integration test
```

## Sử dụng

### 1. Chạy scan tools trước

```bash
# Checkov
docker run --rm -v $(pwd):/tf bridgecrew/checkov \
  -d /tf --output json > checkov_output.json

# tfsec
docker run --rm -v $(pwd):/tf aquasec/tfsec /tf \
  --format json > tfsec_output.json

# Trivy
docker run --rm -v $(pwd):/tf aquasec/trivy \
  config /tf --format json > trivy_output.json
```

### 2. Chạy auto-fix

```bash
python autofix.py \
  --tf-files      ./main.tf \
  --checkov ./checkov_output.json \
  --tfsec   ./tfsec_output.json \
  --trivy   ./trivy_output.json \
  --out-dir ./fix_output \
  --severity LOW          # hoặc LOW,MEDIUM
```

### 3. Dry-run (preview, không ghi file)

```bash
python autofix.py --tf ./main.tf --tfsec ./tfsec.json --dry-run
```

### 4. Output

```
fix_output/
├── main_fixed.tf       # File đã được patch
├── PR_SUMMARY.md       # Markdown report cho PR description
├── PR_SUMMARY.html     # HTML report (dark theme)
└── fix_report.json     # Machine-readable full report
```

## Fix rules có sẵn

| Check ID | Tool | Severity | Fix |
|----------|------|----------|-----|
| CKV_AWS_8 | Checkov | HIGH | EBS root encrypted=true |
| CKV_AWS_3 | Checkov | HIGH | EBS volume encrypted=true |
| CKV_AWS_79 | Checkov | MEDIUM | EC2 IMDSv2 metadata_options |
| CKV_AWS_126 | Checkov | LOW | EC2 monitoring=true |
| CKV_AWS_18 | Checkov | LOW | S3 access logging block |
| CKV_AWS_21 | Checkov | LOW | S3 versioning enabled=true |
| CKV_AWS_36 | Checkov | LOW | CloudTrail log validation=true |
| CKV_AWS_35 | Checkov | LOW | CloudTrail CloudWatch ARN |
| CKV_AWS_129 | Checkov | LOW | RDS auto_minor_version_upgrade=true |
| CKV_AWS_133 | Checkov | LOW | RDS backup_retention_period=7 |
| aws-ec2-enable-at-rest-encryption | tfsec | HIGH | EBS encrypted |
| aws-ec2-no-public-ip | tfsec | LOW | associate_public_ip_address=false |
| aws-s3-enable-versioning | tfsec | LOW | S3 versioning |
| aws-s3-enable-logging | tfsec | LOW | S3 logging |
| aws-s3-no-public-acl | tfsec | HIGH | S3 acl=private |
| aws-cloudtrail-enable-log-validation | tfsec | LOW | CloudTrail validation |
| aws-rds-enable-minor-version-upgrade | tfsec | LOW | RDS minor upgrade |
| aws-rds-specify-backup-retention | tfsec | LOW | RDS backup retention |
| AVD-AWS-0131 | Trivy | HIGH | EC2 IMDSv2 |

## Thêm fix rule mới

Trong `patchers/tf_patcher.py`, thêm vào `FIX_REGISTRY`:

```python
"CKV_AWS_XYZ": FixRule(
    "CKV_AWS_XYZ",
    "Tên check",
    "LOW",                          # severity
    lambda c, f: _set_attribute_in_block(
        c, *_parse_resource(f), "attribute_name", "value"
    ),
),
```

## Tích hợp CI/CD (Gitea + Woodpecker)

```yaml
# .woodpecker/iac-pipeline.yml

# Prerequisites (Woodpecker UI → Repo Settings → Secrets):
#   GITEA_TOKEN  — Personal Access Token với quyền repo:write + issue:write
#   GITEA_URL    — http://192.168.154.129:3000   (hoặc domain Gitea của bạn)

# Woodpecker tự inject CI_REPO_OWNER, CI_REPO_NAME, CI_COMMIT_BRANCH
# vào mọi step — không cần khai báo thêm.
# dirft-check dự kiến
  drift-check:
    image: hashicorp/terraform
    commands:
      - cp fix_output/main_fixed.tf main.tf
      - terraform init
      - terraform plan   # Phải pass trước khi merge
```

## ⚠️ Config Drift Warning

- Luôn chạy `terraform plan` trên `main_fixed.tf` trước khi apply
- Không auto-commit thẳng vào `main` — dùng feature branch + PR review
- Với HIGH/CRITICAL: framework **không tự fix**, chỉ report để review thủ công
