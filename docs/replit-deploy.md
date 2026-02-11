# Replit Deployment Checklist

## Runtime binding and ports
- Web server listens on `0.0.0.0` and uses `PORT` from environment (`server/index.ts`).
- Python backend listens on `0.0.0.0:8000` behind the Node proxy (`server/index.ts`).
- Fast health route is available at `/healthz`.

## Commands
- TypeScript check: `npm run check`
- Build: `npm run build`
- Start (prod): `npm run start`
- Release gate (fails on skipped guarded tests): `npm run release:gate`
- Replit smoke test (expects app running): `npm run smoke:replit`

## Release caveat gate
- Gate ID: `ENV-PARITY-DISAMBIGUATION`
- Command: `scripts/ci_release_gate.sh`
- Purpose: fail deployment if guarded disambiguation tests are skipped.

## Environment
- `DATABASE_URL` must be set (Replit Postgres connection string).
