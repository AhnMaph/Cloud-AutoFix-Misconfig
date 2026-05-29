#!/bin/bash
# ============================================================
# setup.sh — Chạy MỘT LẦN sau khi clone repo này về VM1
# Thực hiện: chuẩn bị thư mục, quyền, copy script vào đúng chỗ
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== VM1 Setup ==="

# 1. Tạo thư mục data với đúng permission
echo "[1] Tạo thư mục data..."
mkdir -p data/gitea data/woodpecker policies scripts
# Gitea chạy với UID 1000
sudo chown -R 1000:1000 data/gitea
chmod 755 data/woodpecker

# 2. Copy opa_eval.py ra /opt/scanner-tools để agent mount được
echo "[2] Cài opa_eval.py vào /opt/scanner-tools..."
sudo mkdir -p /opt/scanner-tools
sudo cp scripts/opa_eval.py /opt/scanner-tools/opa_eval.py
sudo chmod 644 /opt/scanner-tools/opa_eval.py

# 3. Kiểm tra .env đã được chỉnh chưa
echo "[3] Kiểm tra .env..."
if grep -q "FILL_AFTER_GITEA_SETUP" .env; then
    echo ""
    echo "  *** QUAN TRỌNG ***"
    echo "  WOODPECKER_GITEA_CLIENT và WOODPECKER_GITEA_SECRET trong .env"
    echo "  vẫn là placeholder. Làm theo bước sau:"
    echo ""
    echo "  Bước A: Khởi động Gitea trước:"
    echo "    docker compose up -d gitea"
    echo "    # Chờ ~30s rồi vào http://<VM1_IP>:3000"
    echo ""
    echo "  Bước B: Vào Gitea → User Settings → Applications"
    echo "    Tạo OAuth2 App:"
    echo "      Name: Woodpecker CI"
    echo "      Redirect URI: http://<VM1_IP>:8000/authorize"
    echo "    → Copy Client ID và Client Secret"
    echo ""
    echo "  Bước C: Sửa .env:"
    echo "    WOODPECKER_GITEA_CLIENT=<client-id>"
    echo "    WOODPECKER_GITEA_SECRET=<client-secret>"
    echo ""
    echo "  Bước D: Bật Woodpecker webhook trong Gitea app.ini:"
    echo "    docker exec gitea bash -c \\"
    echo "      'echo -e \"\\n[webhook]\\nALLOWED_HOST_LIST=*\" >> /data/gitea/conf/app.ini'"
    echo "    docker restart gitea"
    echo ""
    echo "  Bước E: Khởi động các service còn lại:"
    echo "    docker compose up -d"
    echo ""
else
    echo "  .env OK — không còn placeholder"
    echo ""
    echo "[4] Khởi động stack..."
    docker compose up -d
    echo ""
    echo "=== Stack đang khởi động ==="
    echo "  Gitea:              http://$(grep VM1_IP .env | cut -d= -f2):3000"
    echo "  Woodpecker CI:      http://$(grep VM1_IP .env | cut -d= -f2):8000"
    echo "  OPA REST API:       http://$(grep VM1_IP .env | cut -d= -f2):8181"
    echo ""
    echo "Kiểm tra trạng thái: docker compose ps"
    echo "Xem log Gitea:       docker compose logs -f gitea"
fi