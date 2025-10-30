# Blue/Green Deployment Operations Runbook

## Quick Reference

| Alert Type        | Severity    | Response Time | Escalation |
| ----------------- | ----------- | ------------- | ---------- |
| Failover Detected | ⚠️ Warning  | 5 minutes     | 15 minutes |
| High Error Rate   | 🔥 Critical | Immediate     | 5 minutes  |
| Watcher Crashed   | 🔥 Critical | Immediate     | 2 minutes  |

---

## Alert: 🔄 Failover Detected

**What it means:** The system automatically switched from one pool (Blue/Green) to the other due to the primary pool failing health checks.

### Immediate Actions (0-5 minutes)

1. **Verify the alert**

```bash
   # Check which pool is currently active
   curl -i http://localhost:8080/version | grep X-App-Pool

   # Expected: Should show the backup pool (e.g., "green")
```

2. **Check the failed pool's health**

```bash
   # If Blue failed, check Blue directly
   curl -i http://localhost:8081/version
   curl -i http://localhost:8081/healthz

   # If Green failed, check Green
   curl -i http://localhost:8082/version
   curl -i http://localhost:8082/healthz
```

3. **Review logs for root cause**

```bash
   # Check Nginx logs
   docker logs nginx --tail 50

   # Check failed app logs
   docker logs blue_app --tail 50   # if Blue failed
   docker logs green_app --tail 50  # if Green failed

   # Check watcher output
   docker logs log_watcher --tail 30
```

### Investigation (5-15 minutes)

4. **Common failure patterns**

   | Symptom              | Likely Cause            | Action                             |
   | -------------------- | ----------------------- | ---------------------------------- |
   | "Connection refused" | App crashed             | Restart container                  |
   | "Timeout"            | App hung/unresponsive   | Restart container                  |
   | "502 Bad Gateway"    | App down during restart | Wait or restart                    |
   | Repeated 500 errors  | Application bug         | Check app logs, rollback if needed |

5. **Check container health**

```bash
   docker ps -a
   docker stats --no-stream
```

6. **Review resource usage**

```bash
   # CPU and memory
   docker stats --no-stream blue_app green_app nginx

   # Disk space
   df -h
```

### Recovery Actions

**Option A: Restart the failed pool**

```bash
# Restart Blue
docker-compose restart blue_app

# Wait 10 seconds
sleep 10

# Verify it's healthy
curl -i http://localhost:8081/healthz
```

**Option B: Manual failback (if primary recovered)**

```bash
# Stop chaos if testing
curl -X POST 'http://localhost:8081/chaos/stop'
curl -X POST 'http://localhost:8082/chaos/stop'

# The system will automatically fail back when primary passes health checks
# Monitor for 2 minutes
watch -n 2 'curl -s http://localhost:8080/version | grep -E "pool|release"'
```

**Option C: Keep running on backup (if primary issue unclear)**

```bash
# No action needed - system is stable on backup
# Schedule investigation during business hours
# Document in incident log
```

### Post-Incident (within 24 hours)

1. Document what happened in your incident log
2. Update monitoring thresholds if this was a false positive
3. If application bug, create ticket for dev team
4. Review and update this runbook based on learnings

---

## Alert: 🚨 High Error Rate Detected

**What it means:** The system is experiencing elevated 5xx errors (default: ≥5 errors in 60 seconds).

### Immediate Actions (0-2 minutes)

1. **Assess severity**

```bash
   # Check current error rate
   docker logs nginx --tail 100 | grep " 5"

   # Count recent errors
   docker logs nginx --tail 100 | grep -c " 5"
```

2. **Identify which pool is erroring**

```bash
   # Check current active pool
   curl -i http://localhost:8080/version

   # Test both pools directly
   curl -i http://localhost:8081/version  # Blue
   curl -i http://localhost:8082/version  # Green
```

3. **Check if failover is needed**

```bash
   # If active pool is returning errors consistently
   # Trigger manual failover by changing ACTIVE_POOL in .env

   # 1. Edit .env
   # Change ACTIVE_POOL=blue to ACTIVE_POOL=green (or vice versa)

   # 2. Reload Nginx
   docker-compose up -d --force-recreate nginx

   # 3. Verify switch
   curl -i http://localhost:8080/version
```

### Investigation (2-10 minutes)

4. **Common error patterns**

   **500 Internal Server Error**

   - Application crash or unhandled exception
   - Check app logs: `docker logs <app> --tail 50`
   - Look for stack traces or error messages

   **502 Bad Gateway**

   - App is down or restarting
   - Check container status: `docker ps -a`

   **503 Service Unavailable**

   - Both pools might be down
   - CRITICAL: Check both apps immediately

   **504 Gateway Timeout**

   - App is too slow or hung
   - Check if app is processing requests: `docker logs <app> -f`

5. **Check for external factors**

```bash
   # Database connectivity (if applicable)
   # API dependencies
   # Network issues
   # Resource exhaustion (CPU, memory, disk)

   docker stats --no-stream
   free -h
   df -h
```

### Recovery Actions

**If one pool is healthy:**

```bash
# Switch to healthy pool (see step 3 above)
# Investigate and fix unhealthy pool
# Test before switching back
```

**If both pools are erroring:**

```bash
# CRITICAL SITUATION
# 1. Check if it's a deployment issue
docker logs blue_app --tail 50
docker logs green_app --tail 50

# 2. Restart both apps
docker-compose restart blue_app green_app

# 3. If still failing, rollback to last known good version
# Edit .env with previous image tags
# docker-compose up -d --force-recreate blue_app green_app

# 4. Escalate to on-call engineer immediately
```

**Temporary mitigation:**

```bash
# If errors are intermittent, adjust Nginx retry behavior
# (requires config change and nginx reload)
```

### Escalation Criteria

Escalate immediately if:

- Both pools are returning errors
- Error rate > 50% of requests
- Unable to identify root cause within 10 minutes
- Customer-facing impact confirmed

---

## Alert: 🔥 Log Watcher Crashed

**What it means:** The monitoring system itself has failed.

### Immediate Actions

1. **Restart the watcher**

```bash
   docker-compose restart watcher

   # Check if it started successfully
   docker logs watcher --tail 20
```

2. **Verify system is still operational**

```bash
   # Test main endpoint
   curl -i http://localhost:8080/version

   # Should still work (you just lost monitoring temporarily)
```

3. **Check for underlying issues**

```bash
   # Disk space (common cause)
   df -h

   # Memory
   free -h

   # Watcher logs for error message
   docker logs watcher
```

### Recovery

- If disk full: Clean up logs and old images

```bash
  docker system prune -a
```

- If configuration error: Check .env file and rebuild

```bash
  docker-compose build watcher
  docker-compose up -d watcher
```

---

## Routine Maintenance

### Daily Health Check

```bash
#!/bin/bash
# Save as: healthcheck.sh

echo "=== Daily Health Check ==="
echo "Date: $(date)"
echo ""

echo "Container Status:"
docker ps --format "table {{.Names}}\t{{.Status}}"
echo ""

echo "Recent Errors (last hour):"
docker logs nginx --since 1h 2>&1 | grep -c " 5"
echo ""

echo "Active Pool:"
curl -s http://localhost:8080/version | grep -o '"pool":"[^"]*"'
echo ""

echo "Resource Usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

Run daily: `./healthcheck.sh`

### Weekly Review

- Check alert history in Slack
- Review error patterns
- Update thresholds if needed
- Test failover manually

### Testing Failover (Controlled)

```bash
# 1. Announce test in team chat
# 2. Trigger chaos on active pool
curl -X POST 'http://localhost:8081/chaos/start?mode=error'

# 3. Watch logs
docker logs watcher -f

# 4. Verify failover happened
curl -i http://localhost:8080/version

# 5. Stop chaos
curl -X POST 'http://localhost:8081/chaos/stop'

# 6. Document results
```

## Useful Commands Cheat Sheet

```bash
# Check active pool
curl -s http://localhost:8080/version | jq .

# View live logs
docker logs -f nginx
docker logs -f watcher

# Restart a service
docker-compose restart <service_name>

# Force recreate (config changes)
docker-compose up -d --force-recreate nginx

# Check all container status
docker-compose ps

# Tail all logs together
docker-compose logs -f

# Emergency stop everything
docker-compose down

# Emergency start everything
docker-compose up -d
```

---

**Last Updated:** 30-10-2025
**Runbook Version:** 1.0  
**Maintained By:** Adaeze Ikemefuna/Hamsa
