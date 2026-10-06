# NEXUS — Personal AI Operating System

NEXUS es una Personal AI para el Nebius Global AI Hackathon 2026. Integra memoria persistente, orquestador de agentes, Trust Engine, permisos con aprobación humana, MCP, Agent Runtime/Sandbox, Always-On/Scheduled Jobs y frontend PWA.

## Arquitectura
Flujo de ejecución: User → Frontend → API → Agent Orchestrator → PlanValidator → TrustEngine → ToolExecutor → MCP/Native → Agent Runtime → Sandbox. LLM produce propuestas, nunca autoriza ni ejecuta directamente.

## Inicio Rápido (Docker)
1. Copiar .env.example a .env y configurar variables
2. docker compose up --build
3. Frontend: http://localhost:3000
4. Backend API: http://localhost:8000
5. API Docs: http://localhost:8000/docs

## Desarrollo Local
- Backend: cd backend && uvicorn app.main:app --reload
- Frontend: cd frontend && npm run dev
- Migraciones DB: cd backend && alembic upgrade head
- Tests: cd backend && python -m pytest

## Seguridad (Fase 13)
Invariantes clave: LLM no autoriza ni ejecuta; TrustEngine obligatorio; autorización de ejecución requerida para herramientas sandbox; sin fallback a host ante fallo de runtime; aislamiento por ownership; fail-closed por defecto. Ver docs/FASE_13_SECURITY_HARDENING.md y docs/FASE_13_THREAT_MODEL.md.

## Deployment (Fase 14)
Stack reproducible con Docker: backend.Dockerfile, frontend.Dockerfile (multi-stage + nginx), docker-compose.yml con PostgreSQL + healthchecks + migraciones automáticas. Ver docs/FASE_14_DEPLOYMENT_DOCKER.md y docs/deployment-checklist.md.

## Componentes Clave
- Memory (persistente, aislada por usuario)
- Agent Orchestrator + PlanValidator + TrustEngine
- NVIDIA Nemotron vía Nebius Token Factory (solo backend)
- Skills/Tools, MCP, Runtime/Sandbox, Always-On/Scheduled Jobs
- Human-in-the-Loop (aprobaciones)
