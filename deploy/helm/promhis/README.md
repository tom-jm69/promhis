# Promhis Helm chart

Deploys Promhis — the durable history layer for Prometheus Alertmanager — onto a Kubernetes cluster. Same single self-hosted image as `docker compose up` (see the main repo's [`docs/self-hosting.md`](../../../docs/self-hosting.md)); this chart just runs it as a Deployment instead.

## Before you install: is there a published image yet?

`.github/workflows/publish.yml` builds and pushes to `ghcr.io/<this repo>` on every push to `main` (tag `latest` + a short commit SHA) and on version tags like `v0.1.0` (tags `0.1.0`, `0.1` too) — but that workflow only actually runs once this repo is pushed to GitHub (see `ROADMAP.md`'s "No GitHub publish yet" note; as of writing, it isn't). Until then, `values.yaml`'s `image.repository` default (`ghcr.io/tom-jm69/promhis`) is a placeholder, not a real pushed image — build and push your own instead:

```bash
docker build -t ghcr.io/<you>/promhis:0.1.0 .
docker push ghcr.io/<you>/promhis:0.1.0
```

Then point `image.repository`/`image.tag` at that. Once this repo is on GitHub and that workflow has run at least once, `image.tag: latest` (or a real version tag) against `ghcr.io/<org>/<repo>` just works.

## Quickstart (bundled Postgres, single instance)

```bash
cat > my-values.yaml <<EOF
image:
  repository: ghcr.io/<you>/promhis
  tag: "0.1.0"
admin:
  password: "a-real-password"
sessionSecret:
  value: "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
EOF

helm install promhis deploy/helm/promhis -f my-values.yaml
```

Postgres is the only supported storage (see the main repo's `ROADMAP.md`) — by default this chart runs its own single-instance Postgres alongside the app (`postgresql.enabled: true`), same bundled-container spirit as `docker-compose.yml`. That gets you two pods (app + Postgres), a `ClusterIP` Service, no ingress, the app's own storage being entirely stateless. Follow the printed NOTES for the admin login and how to reach it.

The bundled Postgres's password is auto-generated on first install and read back from the cluster on every later `helm upgrade` (never re-rolled); override it with `postgresql.auth.password` if you need a known value.

## Using your own Postgres instead

The bundled instance is convenient, not durable — this chart doesn't back up its PVC for you. For anything you actually depend on:

```yaml
postgresql:
  enabled: false

database:
  url: "postgresql+asyncpg://user:pass@your-postgres-host/promhis"
  # or, better, reference a secret you already created:
  # existingSecret: my-postgres-secret
  # existingSecretKey: database-url
```

`replicaCount` can go above 1 safely either way — the app itself holds no state, so scaling out just means more pods talking to the same Postgres (bundled or external).

## Secrets: bring your own, or let the chart create them

By default the chart creates one `Secret` (named after the release) holding whatever of `admin.password`, `sessionSecret.value`, `webhook.token`, `metrics.password`, `database.url`, `license.content`, and `digest.smtp.password` you set directly in values — convenient for a quick install, but those values land in `helm get values`/your values file in plaintext. For anything beyond a demo, create your own `Secret`s out of band and point the matching `existingSecret` (+ `existingSecretKey`) field at them instead; the chart never creates a key the corresponding `existingSecret` is already covering. The bundled Postgres's own password lives in a second, separate `Secret` (`<release>-postgres`) for the same reason — only relevant while `postgresql.enabled` is true.

`admin.password` and `sessionSecret.value` (or their `existingSecret` equivalents) are the only two the chart actually requires — it refuses to install with neither set.

## Ingress

Off by default (`ingress.enabled: false`, `ClusterIP` Service). A typical ingress-nginx + cert-manager setup:

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: promhis.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: promhis-tls
      hosts:
        - promhis.example.com

trustProxy: true # ingress-nginx sits in front now — honor its X-Forwarded-* headers
publicBaseUrl: "https://promhis.example.com"
```

## Enterprise license

Set `license.content` to the raw JSON of a signed license file (see the main repo's [`docs/licensing.md`](../../../docs/licensing.md)), or `license.existingSecret`/`license.existingSecretKey` to mount one you've already created as a Secret. Either way it's mounted read-only at `/etc/promhis/license.json` and `PROMHIS_LICENSE_FILE` is set to match automatically.

## Scraping Promhis's own `/metrics`

`metrics.enabled` is on by default (unauthenticated, same posture as `/healthz`). If you run the Prometheus Operator, set `metrics.serviceMonitor.enabled: true` to get a `ServiceMonitor` scraping it; set `metrics.user`/`metrics.password` (or their `existingSecret` form) first if you also want `/metrics` to require Basic auth, in which case the `ServiceMonitor` is generated with matching `basicAuth`.

## Testing this chart locally (kind)

```bash
deploy/helm/promhis/hack/kind-up.sh    # creates a throwaway kind cluster, builds+loads the image, installs
kubectl --context kind-promhis-test port-forward svc/promhis 18000:8000
open http://localhost:18000            # login: admin / kindtestpass

deploy/helm/promhis/hack/kind-down.sh  # tears everything back down
```

Requires `docker`, `kind`, `kubectl`, and `helm` locally. `hack/test-values.yaml` holds dummy credentials for this only — never reuse them for anything real.

## Values reference

See `values.yaml` directly — every field has an inline comment. The main repo's [`docs/configuration.md`](../../../docs/configuration.md) describes what each underlying `PROMHIS_*` setting actually does; this chart is a mechanical mapping onto that, not a separate configuration surface.
