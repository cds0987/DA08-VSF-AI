# Deploy artifacts

These files are the service-owned deploy artifacts for `rag-service`.

## Included

- `k8s/configmap.yaml`: non-secret runtime defaults.
- `k8s/secret.example.yaml`: secret template for production wiring.
- `k8s/migration-job.yaml`: controlled `alembic upgrade head` step.
- `k8s/deployment.yaml`: app deployment with `livez` and `readyz` probes.
- `k8s/service.yaml`: cluster service.

## Rollout verify

1. Apply config and secret.
2. Run `migration-job.yaml` and wait for success.
3. Roll out `deployment.yaml`.
4. Verify the running pod image digest matches the intended release.
5. Verify `GET /readyz` returns `200`.
6. Verify `alembic current` inside the release matches `head`.

The Kubernetes manifests intentionally use an immutable image reference placeholder:
replace `ghcr.io/example/rag-service@sha256:REPLACE_ME` with the real pushed digest.
