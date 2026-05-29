provider "aws" {
  region     = "us-east-1"
  # ❌ error CHÍ MẠNG 1: Lộ Access Key và Secret Key ngay trong code (Hardcoded Secrets)
  # Trivy và Checkov sẽ báo ĐỎ rực ở đây ngay lập tức.
  access_key = "AKIAIOSFODNN7EXAMPLE"
  secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
}

# ----------------------------------------------------------
# 1. EC2 INSTANCE BỊ LỖI BẢO MẬT NETWORK
# ----------------------------------------------------------
resource "aws_security_group" "bad_sg" {
  name        = "allow_all_ssh_and_http"
  description = "Security group loi bao mat de test Lab"

  # ❌ LỖI CHÍ MẠNG 2: Mở port SSH (22) công khai cho toàn bộ Internet (0.0.0.0/0)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] 
  }

  # ❌ LỖI CHÍ MẠNG 3: Mở port Database (3306) cho toàn Internet thay vì chỉ cho nội bộ
  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "vulnerable_ec2" {
  ami           = "ami-0c55b159cbfafe1f0" # Ubuntu Server
  instance_type = "t2.micro"
  security_groups = [aws_security_group.bad_sg.name]

  # ❌ LỖI 4: Ổ đĩa gốc (Root Block Device) không được mã hóa dữ liệu
  root_block_device {
    encrypted = false
  }

  tags = {
    Name = "Vulnerable-Demo-Instance"
  }
}

# ----------------------------------------------------------
# 2. S3 BUCKET BỊ LỘ DỮ LIỆU (PUBLIC)
# ----------------------------------------------------------
resource "aws_s3_bucket" "leaky_bucket" {
  bucket = "my-super-secret-devsecops-lab-bucket"
}

# ❌ LỖI CHÍ MẠNG 5: Cho phép Public công khai S3 Bucket 
resource "aws_s3_bucket_public_access_block" "bad_access" {
  bucket = aws_s3_bucket.leaky_bucket.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# ❌ LỖI 6: Không cấu hình Server-Side Encryption (Mã hóa phía máy chủ) cho S3
# Checkov và tfsec sẽ quét ra lỗi thiếu cấu hình mã hóa nền.
