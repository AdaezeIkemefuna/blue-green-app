import os, re, time, requests
from datetime import datetime, timedelta
from collections import deque

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
NGINX_LOG_PATH = os.getenv("NGINX_LOG_PATH", "/var/log/nginx/access.log")
ERROR_THRESHOLD = int(os.getenv("ERROR_THRESHOLD", "5"))
CHECK_WINDOW_SECONDS = int(os.getenv("CHECK_WINDOW_SECONDS", "60"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))

error_timestamps = deque()
last_alert_time = {"failover": datetime.min, "error_rate": datetime.min}
current_pool = None

LOG_PATTERN = re.compile(r'.*" (?P<status>\d{3}) \d+ "[^"]*" "[^"]*" pool=(?P<pool>\S+)')

def send_slack(message, severity="warning"):
    if not SLACK_WEBHOOK_URL:
        return
    emoji = "🔥" if severity == "critical" else "⚠️"
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": f"{emoji} {message}"}, timeout=5)
    except:
        pass

def cooldown_ok(kind):
    now = datetime.now()
    if (now - last_alert_time[kind]).total_seconds() < ALERT_COOLDOWN_SECONDS:
        return False
    last_alert_time[kind] = now
    return True

def handle_log(line):
    global current_pool
    
    m = LOG_PATTERN.search(line)
    if not m:
        return
    
    pool = m.group("pool")
    status = int(m.group("status"))
    
    if pool == "-":
        return
    
    if current_pool and pool != current_pool:
        if cooldown_ok("failover"):
            send_slack(f"Failover: {current_pool} → {pool}", "warning")
        current_pool = pool
    elif not current_pool:
        current_pool = pool

    if 500 <= status < 600:
        now = datetime.now()
        error_timestamps.append(now)
        cutoff = now - timedelta(seconds=CHECK_WINDOW_SECONDS)
        
        while error_timestamps and error_timestamps[0] < cutoff:
            error_timestamps.popleft()

        if len(error_timestamps) >= ERROR_THRESHOLD and cooldown_ok("error_rate"):
            send_slack(f"High error rate: {len(error_timestamps)} in {CHECK_WINDOW_SECONDS}s", "critical")

def tail_log():
    while not os.path.exists(NGINX_LOG_PATH):
        time.sleep(2)

    with open(NGINX_LOG_PATH, "r") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                handle_log(line.strip())
            else:
                time.sleep(0.2)

if __name__ == "__main__":
    try:
        tail_log()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        send_slack(f"Watcher crashed: {e}", "critical")