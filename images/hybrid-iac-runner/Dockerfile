FROM python:3.11-slim

ARG TERRAFORM_VERSION=1.15.6
ARG TFSEC_VERSION=1.28.14

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    git \
    jq \
    ca-certificates \
    gnupg \
    bash \
    openssh-client \
    tar \
    gzip \
    coreutils \
    findutils \
    grep \
    sed \
    && rm -rf /var/lib/apt/lists/*

# Terraform
RUN curl -fsSL -o /tmp/terraform.zip \
    https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm -f /tmp/terraform.zip \
    && terraform version

# tfsec
RUN curl -fsSL -o /usr/local/bin/tfsec \
    https://github.com/aquasecurity/tfsec/releases/download/v${TFSEC_VERSION}/tfsec-linux-amd64 \
    && chmod +x /usr/local/bin/tfsec \
    && tfsec --version

# Trivy via official apt repository
RUN curl -fsSL https://aquasecurity.github.io/trivy-repo/deb/public.key \
    | gpg --dearmor -o /usr/share/keyrings/trivy.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb generic main" \
    > /etc/apt/sources.list.d/trivy.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends trivy \
    && rm -rf /var/lib/apt/lists/* \
    && trivy --version

# Python tools used by pipeline scripts
RUN pip install --no-cache-dir \
    checkov \
    colorama \
    requests \     
    PyYAML \
    python-openstackclient

WORKDIR /woodpecker/src

CMD ["/bin/sh"]