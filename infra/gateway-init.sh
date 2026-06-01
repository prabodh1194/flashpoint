#!/bin/bash
set -euo pipefail

# Install Python + uv
dnf install -y python3.12 git
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Clone repo (or pull if exists)
REPO_DIR="/opt/flashpoint"
REPO_BRANCH="${branch}"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch origin
  git -C "$REPO_DIR" checkout "$REPO_BRANCH"
  git -C "$REPO_DIR" pull origin "$REPO_BRANCH"
else
  git clone --branch "$REPO_BRANCH" https://github.com/prabodh1194/flashpoint.git "$REPO_DIR"
fi

# Install gateway deps
cd "$REPO_DIR/gateway"
uv sync --python python3.12

# Write environment config
cat > /etc/flashpoint-gateway.env <<EOF
FLASHPOINT_ECS_CLUSTER=${cluster}
FLASHPOINT_DRIVER_TASK_DEF=${task_def}
FLASHPOINT_SUBNETS=${subnets}
FLASHPOINT_SECURITY_GROUP=${security_group}
AWS_DEFAULT_REGION=${region}
EOF

# Install and start systemd service
cat > /etc/systemd/system/flashpoint-gateway.service <<'UNIT'
[Unit]
Description=Flashpoint Gateway
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/flashpoint/gateway
EnvironmentFile=/etc/flashpoint-gateway.env
ExecStart=/opt/flashpoint/gateway/.venv/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable flashpoint-gateway
systemctl start flashpoint-gateway
