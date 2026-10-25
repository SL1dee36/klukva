"""
Deployment script to upload and configure Klukva on remote server 72.56.22.5
"""

import os
import sys
import paramiko

# Ensure UTF-8 stdout on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST = "72.56.22.5"
USER = "root"
PASS = "cTe^5XiRH-?t7Q"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

def deploy():
    print(f"Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=22, username=USER, password=PASS, timeout=15)
    sftp = ssh.open_sftp()

    print("Uploading files via SFTP...")
    def upload_file(local_path, remote_path):
        print(f"  Uploading {os.path.basename(local_path)} -> {remote_path}")
        sftp.put(local_path, remote_path)

    # Base files
    upload_file(os.path.join(LOCAL_DIR, "main.py"), "/opt/klukva/main.py")
    upload_file(os.path.join(LOCAL_DIR, "requirements.txt"), "/opt/klukva/requirements.txt")
    if os.path.exists(os.path.join(LOCAL_DIR, "klukva_db.json")):
        upload_file(os.path.join(LOCAL_DIR, "klukva_db.json"), "/opt/klukva/klukva_db.json")

    # Backend files
    for f in ["__init__.py", "db.py", "auth.py", "routes.py"]:
        local_p = os.path.join(LOCAL_DIR, "backend", f)
        if os.path.exists(local_p):
            upload_file(local_p, f"/opt/klukva/backend/{f}")

    # Frontend files
    for f in ["index.html", "style.css", "app.js"]:
        local_p = os.path.join(LOCAL_DIR, "frontend", f)
        if os.path.exists(local_p):
            upload_file(local_p, f"/opt/klukva/frontend/{f}")

    sftp.close()
    print("Files uploaded successfully.")

    def run_cmd(cmd):
        print(f"\n[EXEC] {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        if out.strip():
            print("[STDOUT]\n" + out.strip())
        if err.strip():
            print("[STDERR]\n" + err.strip())
        return out, err

    # 1. Install dependencies in virtualenv
    run_cmd("/opt/klukva/venv/bin/pip install -r /opt/klukva/requirements.txt")

    # 2. Systemd service setup
    service_content = """[Unit]
Description=Klukva Task Tracker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/klukva
ExecStart=/opt/klukva/venv/bin/python main.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    # Write service file
    sftp = ssh.open_sftp()
    with sftp.file("/etc/systemd/system/klukva.service", "w") as f:
        f.write(service_content)
    sftp.close()

    run_cmd("systemctl daemon-reload && systemctl enable --now klukva.service && systemctl restart klukva.service")

    # 3. Configure Nginx
    nginx_conf = """server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name klu.nazlab.tech 72.56.22.5 _;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:3002;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
"""
    sftp = ssh.open_sftp()
    with sftp.file("/etc/nginx/sites-available/klukva", "w") as f:
        f.write(nginx_conf)
    sftp.close()

    run_cmd("rm -f /etc/nginx/sites-enabled/default && ln -sf /etc/nginx/sites-available/klukva /etc/nginx/sites-enabled/klukva")
    run_cmd("nginx -t && systemctl enable --now nginx && systemctl reload nginx")

    # 4. Check services status
    run_cmd("systemctl status klukva --no-pager")
    run_cmd("curl -I http://127.0.0.1:3002")
    run_cmd("curl -I http://127.0.0.1:80")

    # 5. Check Telegram bot (lumibot) status
    print("\n--- Checking Telegram Bot (lumibot) Status ---")
    run_cmd("ps aux | grep lumibot | grep -v grep")

    ssh.close()
    print("\n>>> DEPLOYMENT COMPLETED! <<<")

if __name__ == "__main__":
    deploy()
