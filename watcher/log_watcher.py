#!/usr/bin/env python3
import os, re, time, requests
from datetime import datetime, timedelta
from collections import deque

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
NGINX_LOG_PATH = os.getenv("NGINX_LOG_PATH", "/var/log/nginx/access.log")
ERROR_THRESHOLD = int(os.getenv("ERROR_THRESHOLD", "5"))
CHECK_WINDOW_SECONDS = int(os.getenv("CHECK_WINDOW_SECONDS", "60"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
USERNAME = os.getenv("USERNAME", "Hamsa")

error_timestamps = deque()
total_requests = deque()
last_alert_time = {"failover": datetime.min, "error_rate": datetime.min}
current_pool = None

LOG_PATTERN = re.compile(
    r'.*" (?P<status>\d{3}) \d+ "[^"]*" "[^"]*" '
    r'pool=(?P<pool>\S+) release=(?P<release>\S+) '
    r'upstream_status=(?P<upstream_status>\S+) '
    r'upstream_addr=(?P<upstream_addr>\S+)'
)

def send_slack(blocks, severity="warning"):
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=5)
    except Exception as e:
        print(f"Slack error: {e}")

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
    upstream_addr = m.group("upstream_addr")

    # Infer pool from upstream_addr if needed
    if pool == "-" and upstream_addr != "-":
        if "8081" in upstream_addr or "blue_app" in upstream_addr:
            pool = "blue"
        elif "8082" in upstream_addr or "green_app" in upstream_addr:
            pool = "green"

    if pool == "-":
        return

    # Detect failover
    if current_pool and pool != current_pool:
        if cooldown_ok("failover"):
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🔄 Failover Detected",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Pool switched:* `{current_pool}` → `{pool}`\n*Detected by:* {USERNAME}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Action Required:*\n• Check health of `{current_pool}` container\n• Review application logs\n• Verify `{pool}` is handling traffic correctly"
                    }
                }
            ]
            send_slack(blocks, "warning")
        current_pool = pool
    elif not current_pool:
        current_pool = pool

    # Track requests for error rate
    now = datetime.now()
    total_requests.append(now)
    cutoff = now - timedelta(seconds=CHECK_WINDOW_SECONDS)

    while total_requests and total_requests[0] < cutoff:
        total_requests.popleft()

    # Track errors
    if 400 <= status < 600:
        error_timestamps.append(now)

        while error_timestamps and error_timestamps[0] < cutoff:
            error_timestamps.popleft()

        total = len(total_requests)
        errors = len(error_timestamps)

        if total >= 10:  # Need at least 10 requests to calculate rate
            error_rate = (errors / total) * 100

            if error_rate >= ERROR_THRESHOLD and cooldown_ok("error_rate"):
                blocks = [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "⚠️ Alert: high_error_rate",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*High Error Rate Detected*\n*Detected by:* {USERNAME}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Error Rate:*\n{error_rate:.2f}% ({errors}/{total} requests)"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Threshold:*\n{ERROR_THRESHOLD}%"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Window:*\n{CHECK_WINDOW_SECONDS} seconds"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Current Pool:*\n`{pool}`"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Action Required:*\n• Check upstream application health\n• Review error logs\n• Consider toggling pools if issue persists"
                        }
                    }
                ]
                send_slack(blocks, "critical")

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
    print(f"🚀 Log watcher started (User: {USERNAME})")
    print(f"📊 Error threshold: {ERROR_THRESHOLD}%, Window: {CHECK_WINDOW_SECONDS}s")
    try:
        tail_log()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        send_slack([{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"🔥 *Watcher Crashed*\n```{e}```"}
        }], "critical")