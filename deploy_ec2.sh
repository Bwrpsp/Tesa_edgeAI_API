#!/usr/bin/env bash
# ==============================================================================
# TopGun Server - 1-Click AWS EC2 Automated Deployment Script
# Supports: Ubuntu 20.04/22.04/24.04 and Amazon Linux 2023 / AL2
# ==============================================================================

set -e

echo "=========================================================="
echo "🚀 Starting TopGun Server EC2 Setup"
echo "=========================================================="

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(logname 2>/dev/null || echo $SUDO_USER)"
if [ -z "$CURRENT_USER" ]; then
    CURRENT_USER="$(whoami)"
fi

echo "[*] Application directory: $APP_DIR"
echo "[*] Service user: $CURRENT_USER"

# 1. Update OS and Install Prerequisites
echo "\n[*] Installing system packages..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv nginx curl git
elif command -v dnf &> /dev/null; then
    sudo dnf update -y
    sudo dnf install -y python3 python3-pip nginx curl git
elif command -v yum &> /dev/null; then
    sudo yum update -y
    sudo yum install -y python3 python3-pip nginx curl git
else
    echo "[-] Unsupported package manager. Please install Python 3 and Nginx manually."
    exit 1
fi

# 2. Setup Python Virtual Environment
echo "\n[*] Setting up Python environment..."
cd "$APP_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 3. Create initial .env if not present
if [ ! -f ".env" ]; then
    echo "[*] Creating default .env configuration..."
    cat <<EOF > .env
ENV=production
APP_NAME="TopGun Benchmark Server"
ADMIN_API_KEY="$(openssl rand -hex 16)"
DATABASE_URL="sqlite+aiosqlite:///./data/topgun.db"
DEFAULT_TEST_QUOTA=5
DEFAULT_GLOBAL_MODE="all"
MAX_SUBMISSION_WINDOW_SECONDS=0
EOF
    echo "[+] Generated random ADMIN_API_KEY in .env"
fi

# Ensure data folders exist
mkdir -p data/images/train data/images/test data/submissions
chown -R "$CURRENT_USER":"$CURRENT_USER" "$APP_DIR"

# 4. Create Systemd Service for FastAPI (Uvicorn)
echo "\n[*] Setting up Systemd Service (topgun.service)..."
SERVICE_FILE="/etc/systemd/system/topgun.service"

sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=TopGun Competition FastAPI Service
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3
EnvironmentFile=$APP_DIR/.env

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable topgun.service
sudo systemctl restart topgun.service

# 5. Configure Nginx Reverse Proxy (Port 80 -> Port 8000)
echo "\n[*] Configuring Nginx Reverse Proxy..."
if [ -d "/etc/nginx/sites-available" ]; then
    NGINX_CONF="/etc/nginx/sites-available/topgun"
    sudo bash -c "cat << 'EOF' > $NGINX_CONF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
EOF"
    sudo rm -f /etc/nginx/sites-enabled/default || true
    sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/topgun
else
    # Amazon Linux / RHEL / CentOS
    NGINX_CONF="/etc/nginx/conf.d/topgun.conf"
    sudo bash -c "cat << 'EOF' > $NGINX_CONF
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
EOF"
fi

sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

# 6. Verify Health
sleep 2
HEALTH_CHECK=$(curl -s http://127.0.0.1/health || echo "FAILED")

echo "\n=========================================================="
echo "✅ DEPLOYMENT FINISHED SUCCESSFULLY!"
echo "=========================================================="
echo "Health status: $HEALTH_CHECK"
echo "\nNext steps:"
echo "1. In AWS EC2 Security Groups: Allow inbound Port 80 (HTTP) from anywhere (or Cloudflare IPs)."
echo "2. In Cloudflare DNS: Point your domain (e.g. api.yourdomain.com) -> EC2 Public IP (Orange Cloud Proxied)."
echo "3. In Cloudflare SSL/TLS: Set mode to 'Flexible' (or 'Full')."
echo "4. Your API is live at: https://your-domain.com"
echo "=========================================================="
