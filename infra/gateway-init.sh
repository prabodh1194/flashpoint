#!/bin/bash
set -euo pipefail

# Install Python + uv
dnf install -y python3.12 python3.12-pip git
pip3.12 install uv

# Clone repo (or pull if exists)
REPO_DIR="/opt/flashpoint"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull
else
  git clone https://github.com/prabodh1194/flashpoint.git "$REPO_DIR"
fi

# Install gateway deps
cd "$REPO_DIR/gateway"
uv sync

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
