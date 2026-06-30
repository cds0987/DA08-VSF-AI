# Admin frontend

Nuxt 4 application on port `3001`. It uses User Service for authentication and
user management, Document Service for document operations, and Query Service
for admin metrics.

## Development

```bash
cp .env.local.example .env.local
npm install
npm run dev
```

## Verification

```bash
npm run build
npm run test:e2e:upload
```

The upload test uses Playwright with system Chrome and mocks Document Service,
so it is safe to run without cloud credentials. See
[frontend-upload-test.md](../../../docs/frontend-upload-test.md) for automated
and manual integration steps.

# frontend/admin — Nuxt 4 — Admin Application · :3001 · standalone app · gọi Document Service + User Service `/users` + Query Service `/admin/metrics`
