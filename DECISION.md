# Implementation Notes

## Getting the Images to Run

First issue I hit was a platform warning when pulling the images. I'm on a Mac (Apple Silicon), but the containers are built for linux/amd64. Docker was complaining about the architecture mismatch, so I added this to both app services in docker-compose.yml:

```yaml
platform: linux/amd64
```

That fixed the warning and got the containers running properly.

## The 404 Problem

Started getting 404s when hitting `http://localhost:8080/version`. Took a bit to figure out, but the problem was in my nginx.conf.template - I was trying to use Jinja-style if/else syntax like `{% if $ACTIVE_POOL = "blue" %}` which envsubst doesn't understand at all.

envsubst only does simple variable substitution with `${VARIABLE}`, it can't do conditionals.

The fix was moving the if/else logic into the docker-compose command itself. Now the shell script checks `$ACTIVE_POOL` and sets `PRIMARY_SERVER` and `BACKUP_SERVER` accordingly, then envsubst just replaces those values. Way simpler.

## Header Visibility Issues

Another weird one - I could see the response headers perfectly fine in terminal with `curl -i`, but when I opened the endpoint in Chrome's dev tools, the custom headers (`X-App-Pool`, `X-Release-Id`) weren't showing up.

I added `proxy_pass_request_headers on;` to the Nginx config thinking maybe that would help, but honestly Chrome still didn't show them. Switched to Safari and suddenly the headers were there. Not sure if it's a Chrome caching thing or what, but the headers were being returned all along - just use curl or Safari to actually see them.

## Testing the Failover

Used curl to test everything:

```bash
# Check baseline - all should be blue
for i in {1..5}; do
  curl -i http://localhost:8080/version | grep "X-App-Pool"
done

# Break blue (had to quote the URL because zsh)
curl -X POST 'http://localhost:8081/chaos/start?mode=error'

# Watch it switch to green
for i in {1..20}; do
  curl -s -i http://localhost:8080/version | grep "X-App-Pool"
  sleep 0.3
done
```

The failover worked - after the first 1-2 requests hit blue and failed, Nginx marked it down and switched everything to green. No 500 errors made it through to the client, which is exactly what the task wanted.

## Key Config Settings

The tight timeouts are what make failover fast:

- `proxy_connect_timeout 2s`
- `proxy_read_timeout 2s`
- `max_fails=2 fail_timeout=5s`

And `proxy_next_upstream error timeout http_500 http_502 http_503 http_504` tells Nginx to retry on the backup server if the primary fails, so the client never sees the error.

## Final Setup

- Blue and Green run on internal port 3000
- Exposed to host as 8081 and 8082 for direct chaos testing
- Nginx on 8080 routes everything based on which pool is active
- Switching pools just means changing ACTIVE_POOL in .env and recreating the nginx container
