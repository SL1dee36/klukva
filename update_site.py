"""
Klukva Update Script
Updates backend and frontend on remote server 72.56.22.5 without touching the database or any other services.

Workflow:
1. Connects to server and stops the website service (systemctl stop klukva.service).
2. Cleans up old files in /opt/klukva EXCEPT the database (klukva_db.json) and virtualenv (venv).
3. Uploads fresh backend and frontend files from local project.
4. Starts the website service (systemctl start klukva.service) and checks status.
"""

import os
import sys
import paramiko

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST = "72.56.22.5"
USER = "root"
PASS = "cTe^5XiRH-?t7Q"
REMOTE_DIR = "/opt/klukva"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))


def update_site():
    print("=" * 60)
    print("  ОБНОВЛЕНИЕ САЙТА KLUKVA НА СЕРВЕРЕ 72.56.22.5")
    print("=" * 60)

    print(f"\n[1/4] Подключение по SSH к {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, port=22, username=USER, password=PASS, timeout=15)
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return False

    def exec_cmd(cmd):
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out, err

    # 1. Stop service
    print("\n[1/4] Остановка сервиса сайта (systemctl stop klukva.service)...")
    exec_cmd("systemctl stop klukva.service")
    status_out, _ = exec_cmd("systemctl is-active klukva.service || true")
    print(f"  Статус сервиса: {status_out}")

    # 2. Delete files except klukva_db.json and venv
    print("\n[2/4] Очистка старых файлов (БД klukva_db.json и venv НЕ затрагиваются)...")
    clean_cmd = (
        "find /opt/klukva -mindepth 1 -maxdepth 1 "
        "! -name 'klukva_db.json' ! -name 'venv' -exec rm -rf {} +"
    )
    exec_cmd(clean_cmd)

    # Recreate subdirectories
    exec_cmd("mkdir -p /opt/klukva/backend /opt/klukva/frontend")
    files_check, _ = exec_cmd("ls -la /opt/klukva")
    print("  Содержимое /opt/klukva после очистки:")
    for line in files_check.split("\n"):
        print(f"    {line}")

    # 3. SFTP upload fresh backend + frontend (NO db!)
    print("\n[3/4] Перенос свежих файлов backend и frontend...")
    sftp = ssh.open_sftp()

    def upload(local_file, remote_file):
        print(f"  -> {os.path.basename(local_file)} => {remote_file}")
        sftp.put(local_file, remote_file)

    upload(os.path.join(LOCAL_DIR, "main.py"), f"{REMOTE_DIR}/main.py")
    upload(os.path.join(LOCAL_DIR, "requirements.txt"), f"{REMOTE_DIR}/requirements.txt")

    for f in ["__init__.py", "db.py", "auth.py", "routes.py"]:
        lp = os.path.join(LOCAL_DIR, "backend", f)
        if os.path.exists(lp):
            upload(lp, f"{REMOTE_DIR}/backend/{f}")

    for f in ["index.html", "style.css", "app.js"]:
        lp = os.path.join(LOCAL_DIR, "frontend", f)
        if os.path.exists(lp):
            upload(lp, f"{REMOTE_DIR}/frontend/{f}")

    sftp.close()
    print("  Все файлы успешно загружены.")

    # 4. Start service
    print("\n[4/4] Запуск сервиса сайта (systemctl start klukva.service)...")
    exec_cmd("systemctl start klukva.service")
    status_out, _ = exec_cmd("systemctl is-active klukva.service || true")
    print(f"  Статус сервиса: {status_out}")

    # Verify HTTP response
    http_code, _ = exec_cmd("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3002/ || true")
    print(f"  Проверка локального ответа (порт 3002): HTTP {http_code}")

    nginx_code, _ = exec_cmd("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/ || true")
    print(f"  Проверка Nginx ответа (порт 80): HTTP {nginx_code}")

    # Verify Telegram bot is intact
    print("\n--- Проверка Telegram-бота (lumibot) ---")
    bot_check, _ = exec_cmd("ps aux | grep lumibot | grep -v grep || true")
    if bot_check:
        print(f"  [OK] Бот активен:\n    {bot_check}")
    else:
        print("  [ВНИМАНИЕ] Процесс бота не найден в выводе ps")

    ssh.close()
    print("\n" + "=" * 60)
    print("  ОБНОВЛЕНИЕ УСПЕШНО ЗАВЕРШЕНО!")
    print("  Сайт доступен: http://72.56.22.5/ или http://klu.nazlab.tech/")
    print("=" * 60)
    return True


if __name__ == "__main__":
    update_site()
