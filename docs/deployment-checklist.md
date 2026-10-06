# Deployment Checklist (Fase 14)

## Security
- [ ] Secrets not in images
- [ ] HTTPS enabled
- [ ] CORS restricted
- [ ] Debug disabled
- [ ] Security headers active
- [ ] Database not publicly exposed

## Application
- [ ] Backend healthy
- [ ] Frontend healthy
- [ ] PostgreSQL healthy
- [ ] Migrations applied
- [ ] Worker (if applicable) healthy

## Functionality
- [ ] Agent Run works
- [ ] Memory works
- [ ] TrustEngine works
- [ ] Permission approval works
- [ ] MCP works
- [ ] Runtime works
- [ ] Always-On works

## Operations
- [ ] Health checks pass
- [ ] Readiness pass
- [ ] Graceful shutdown works
- [ ] Logs accessible
- [ ] Request IDs work
- [ ] AgentRun IDs work
- [ ] Scheduled jobs survive restart
- [ ] Worker recovery validated
