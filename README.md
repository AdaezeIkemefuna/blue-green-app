# Blue/Green Deployment with Nginx

A blue/green deployment setup using Docker Compose and Nginx for zero-downtime failover between two Node.js application instances.

## What This Does

- Runs two identical Node.js apps (Blue and Green) behind an Nginx reverse proxy
- Automatically fails over to the backup instance if the primary goes down
- No client-visible errors during failover
- Manual switching between blue/green pools via environment variable

## Prerequisites

- Docker and Docker Compose installed
- Mac users: The setup includes `platform: linux/amd64` for Apple Silicon compatibility

## Quick Start (How to run it locally)

1. **Clone the repo**

```bash
   git clone https://github.com/AdaezeIkemefuna/blue-green-app.git
   cd blue-green-app
```

2. **Create your environment file**

```bash
   cp .env.example .env
```

The default values should work fine, but you can customize:

- `ACTIVE_POOL`: Which instance is primary (`blue` or `green`)
- `RELEASE_ID_BLUE` / `RELEASE_ID_GREEN`: Version identifiers returned in headers
- Image references if you want to use different versions

3. **Start everything**

```bash
   docker-compose up -d
```

4. **Test it's working**

```bash
   curl -i http://localhost:8080/version
```

You should see:

- Status: `200 OK`
- Header: `X-App-Pool: blue` (or whatever's active)
- Header: `X-Release-Id: 1.0` (or your configured value)

## Available Endpoints

### Main Service (through Nginx)

- `http://localhost:8080/version` - Returns version info with pool and release headers

### Direct App Access (for testing/chaos)

- `http://localhost:8081/version` - Blue instance directly
- `http://localhost:8082/version` - Green instance directly
- `http://localhost:8081/healthz` - Blue health check
- `http://localhost:8082/healthz` - Green health check

### Chaos Testing

Simulate downtime on either instance:

```bash
# Make Blue start returning errors
curl -X POST 'http://localhost:8081/chaos/start?mode=error'

# Stop chaos
curl -X POST 'http://localhost:8081/chaos/stop'
```

## Testing Failover

Here's how to verify automatic failover works:

```bash
# 1. Verify Blue is active and working
for i in {1..5}; do
  curl -s http://localhost:8080/version | grep -o '"pool":"[^"]*"'
done
# Should show pool: blue for all 5 requests

# 2. Break Blue
curl -X POST 'http://localhost:8081/chaos/start?mode=error'

# 3. Watch it automatically switch to Green
for i in {1..10}; do
  echo "Request $i:"
  curl -s http://localhost:8080/version | grep -o '"pool":"[^"]*"'
  sleep 0.5
done
# After first 1-2 requests, should switch to pool: green

# 4. Verify no errors reach the client
for i in {1..20}; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/version
done
# All should be 200, even during failover

# 5. Clean up
curl -X POST 'http://localhost:8081/chaos/stop'
```

## Switching Active Pool Manually

To switch which instance is primary:

1. Edit `.env` and change `ACTIVE_POOL=blue` to `ACTIVE_POOL=green`

2. Restart Nginx:

```bash
   docker-compose up -d --force-recreate nginx
```

3. Test:

```bash
   curl -i http://localhost:8080/version
```

Should now show `X-App-Pool: green`

## How It Works

- **Nginx upstream**: Configured with primary/backup servers
- **Health checking**: Nginx monitors for failures (`max_fails=2`, `fail_timeout=5s`)
- **Auto-retry**: If primary fails, Nginx automatically retries on backup (`proxy_next_upstream`)
- **Fast failover**: Tight timeouts (2s) ensure quick failure detection
- **Zero downtime**: Client requests succeed even during failover

## Troubleshooting

**Can't see headers in browser?**

- Use `curl -i` instead - some browsers cache or hide custom headers
- Try Safari if Chrome doesn't show them

**404 errors?**

- Check containers are running: `docker-compose ps`
- Verify Nginx config was generated: `docker exec nginx cat /etc/nginx/nginx.conf`

**Failover not working?**

- Check Nginx logs: `docker logs nginx`
- Verify chaos was triggered: `curl -i http://localhost:8081/version` should return 500

**Platform warnings on Mac?**

- Already handled with `platform: linux/amd64` in docker-compose.yml

## Project Structure

```
.
├── docker-compose.yml          # Container orchestration
├── nginx.conf.template         # Nginx configuration template
├── .env.example               # Environment variables template
└── README.md                  # This file
```

## Stopping Everything

```bash
docker-compose down
```

Or to remove volumes too:

```bash
docker-compose down -v
```

STAGE 3

# Blue/Green Deployment with Automated Monitoring

## Slack Integration Setup

This project includes real-time Slack notifications for deployment events and errors.

### Prerequisites

- A Slack workspace where you have permission to add webhooks
- Access to Slack's Incoming Webhooks app

### Setup Steps

1. **Create a Slack Webhook URL**

   - Go to your Slack workspace: https://api.slack.com/apps
   - Click "Create New App" → "From scratch"
   - Name your app (e.g., "Blue-Green Monitor") and select your workspace
   - Navigate to "Incoming Webhooks" in the left sidebar
   - Toggle "Activate Incoming Webhooks" to **On**
   - Click "Add New Webhook to Workspace"
   - Select the channel where you want alerts (e.g., `#deployments`)
   - Copy the generated webhook URL (starts with `https://hooks.slack.com/services/...`)

2. **Configure Your Environment**

   Create or update your `.env` file in the project root:

   ```bash
   # Slack Configuration
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

   # Alert Thresholds
   ERROR_THRESHOLD=5
   CHECK_WINDOW_SECONDS=60
   ALERT_COOLDOWN_SEC=300

   # Other configs...
   ACTIVE_POOL=blue
   BLUE_IMAGE=your-image:blue
   GREEN_IMAGE=your-image:green
   PORT=3000
   ```

3. **Test Your Configuration**

   ```bash
   # Start the services
   docker-compose up -d

   # Trigger a test failover
   ./test_failover.sh

   # Check Slack for alerts
   ```

### Alert Types

The system sends three types of Slack alerts:

| Alert Type               | Severity | Trigger                                               |
| ------------------------ | -------- | ----------------------------------------------------- |
| **Failover Detected** 🔄 | Warning  | When traffic switches from blue → green or vice versa |
| **High Error Rate** 🚨   | Critical | When 5xx errors exceed threshold (default: 5 in 60s)  |
| **Watcher Crash** 🔥     | Critical | If the log monitoring service fails                   |

### Customizing Alert Behavior

Adjust these environment variables in your `.env` file:

```bash
# Number of errors before triggering an alert
ERROR_THRESHOLD=5

# Time window for counting errors (seconds)
CHECK_WINDOW_SECONDS=60

# Minimum time between repeated alerts (seconds)
ALERT_COOLDOWN_SEC=300
```

### Troubleshooting

**Not receiving alerts?**

1. Verify webhook URL is correct in `.env`
2. Check watcher logs: `docker logs log_watcher`
3. Test webhook manually:
   ```bash
   curl -X POST $SLACK_WEBHOOK_URL \
     -H 'Content-Type: application/json' \
     -d '{"text":"Test from blue-green deployment"}'
   ```

**Too many alerts?**

- Increase `ALERT_COOLDOWN_SEC` (default: 300)
- Increase `ERROR_THRESHOLD` (default: 5)

**Missing failover alerts?**

- Check nginx logs show correct pool names: `docker logs nginx | tail`
- Verify log watcher is running: `docker ps | grep watcher`

### Security Notes

⚠️ **Never commit your `.env` file to version control!**

Add to `.gitignore`:

```
.env
.env.local
```

For production deployments:

- Use secret management tools (AWS Secrets Manager, HashiCorp Vault, etc.)
- Rotate webhook URLs periodically
- Restrict Slack app permissions to minimum required scope
