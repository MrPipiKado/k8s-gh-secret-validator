# GitHub Token Validator for Kubernetes Secrets

Reads GitHub tokens out of Kubernetes secrets and reports when each one expires,
so an expired token never silently breaks CI/automation. Designed to run as a
Kubernetes **CronJob**, but works as a one-off CLI too.

## How it works

1. You provide a YAML config listing which secrets and which keys hold tokens.
2. The app reads those secrets from the cluster using the official `kubernetes`
   Python client (no `kubectl` shell-out — in-cluster ServiceAccount auth, with a
   local kubeconfig fallback for development).
3. For each token it calls GitHub's `GET /rate_limit` and reads the
   `GitHub-Authentication-Token-Expiration` response header. This header is
   returned on any authenticated request, works for every token type, and does
   not consume rate limit.
4. Results are printed as a table. Optionally, an MS Teams alert is sent for
   tokens that are expired/expiring/invalid (off by default).

### Supported secret shapes

| Secret type                       | Where the token lives                              |
|-----------------------------------|----------------------------------------------------|
| `Opaque`                          | A plain key, e.g. `token: ghp_...`                 |
| `kubernetes.io/dockerconfigjson`  | Nested under `.dockerconfigjson` → `auths.<registry>` (`password`, or base64 `auth` = `user:token`). One token per registry. |

Credentials that aren't GitHub tokens (e.g. Docker Hub) are reported as `SKIPPED`
rather than sent to GitHub.

### Statuses

`OK` · `WARN` (expires within `warn_days`) · `EXPIRED` · `INVALID` (GitHub
rejected it) · `NO_EXPIRY` (valid, no expiration) · `SKIPPED` (not a GitHub
token) · `ERROR` (missing secret/key, network, RBAC, …). A single bad secret
never aborts the run.

## Configuration

See [`config.example.yaml`](config.example.yaml):

```yaml
warn_days: 7
github_api_url: https://api.github.com   # override for GitHub Enterprise
secrets:
  - namespace: default
    name: github-creds
    keys: [token]
  - namespace: default
    name: ghcr-pull
    keys: [".dockerconfigjson"]
notifiers:
  teams:
    enabled: false                       # off by default
    webhook_url: ""                      # or inject via TEAMS_WEBHOOK_URL
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Try the bundled examples (apply the sample secrets first; replace the
# placeholder tokens with real ones to see live expiry):
kubectl apply -f examples/secret-plain.yaml -f examples/secret-dockerconfigjson.yaml
python main.py --config examples/config-combined.yaml
```

CLI flags: `--config` (required), `--warn-days N` (override), `--json` (also emit
JSON), `--fail-on-expiring` (exit non-zero if any EXPIRED/WARN/INVALID),
`-v` (debug).

## Deploy with Helm (recommended)

The chart in [`chart/token-validator`](chart/token-validator) templatizes the
ServiceAccount, RBAC, ConfigMap, optional Teams Secret, and CronJob — all driven
by [`values.yaml`](chart/token-validator/values.yaml).

```bash
# 1. Build & push the image (adjust registry).
docker build -t <registry>/token-validator:0.1.0 .
docker push <registry>/token-validator:0.1.0

# 2. Install, pointing at your image and the secrets to watch.
helm install token-validator chart/token-validator \
  --namespace platform --create-namespace \
  --set image.repository=<registry>/token-validator \
  --set image.tag=0.1.0

# Trigger a manual run to verify:
kubectl create job --from=cronjob/token-validator token-validator-manual -n platform
kubectl logs -l app.kubernetes.io/instance=token-validator -n platform --tail=-1
```

The entire **application config is passed through chart values**: the `config:`
tree mirrors the app's `config.yaml` one-to-one (snake_case keys) and is rendered
verbatim into the mounted ConfigMap, so any config field is settable via values —
no template edits needed.

| Value | Default | Purpose |
|-------|---------|---------|
| `schedule` | `0 8 * * *` | CronJob cron schedule |
| `config` | example | **Full app config**, rendered verbatim (`warn_days`, `github_api_url`, `secrets`, `notifiers.teams.enabled`) |
| `config.secrets` | example | List of `{namespace, name, keys}` to inspect |
| `rbac.scope` | `cluster` | `cluster` (read secrets in any namespace) or `namespace` (release ns only) |
| `teamsWebhook.webhookUrl` / `teamsWebhook.existingSecret` | `""` | Webhook delivery: inline (chart creates a Secret) or reference an existing Secret; injected as `TEAMS_WEBHOOK_URL` |

Supply your whole config in a values file:

```yaml
# my-values.yaml
config:
  warn_days: 14
  github_api_url: https://api.github.com
  secrets:
    - namespace: prod
      name: ci-bot
      keys: [token]
    - namespace: prod
      name: ghcr-pull
      keys: [".dockerconfigjson"]
  notifiers:
    teams:
      enabled: true
teamsWebhook:
  webhookUrl: https://outlook.office.com/webhook/...
```

```bash
helm install token-validator chart/token-validator -n platform --create-namespace \
  --set image.repository=<registry>/token-validator --set image.tag=0.1.0 \
  -f my-values.yaml
```

## Deploy with raw manifests

The plain manifests in [`deploy/`](deploy/) are an alternative to Helm:

```bash
kubectl apply -f deploy/      # edit deploy/configmap.yaml + image first
```

RBAC ([`deploy/rbac.yaml`](deploy/rbac.yaml)) grants the ServiceAccount `get` on
`secrets` cluster-wide because the config can target multiple namespaces. If all
target secrets live in one namespace, tighten this to a namespaced `Role` (or set
`rbac.scope=namespace` in the chart).

### Enabling MS Teams alerts

1. Set `notifiers.teams.enabled: true` in the ConfigMap.
2. Provide the webhook URL via `webhook_url` in config, or inject
   `TEAMS_WEBHOOK_URL` from a Secret (see the commented `env` block in
   [`deploy/cronjob.yaml`](deploy/cronjob.yaml)).

Alerts are sent only when there are actionable rows (EXPIRED/WARN/INVALID) — a
healthy run sends nothing.

## Tests

```bash
pip install pytest
python -m pytest
```

Covers token extraction (plain + dockerconfigjson, both `password` and base64
`auth` forms), status logic, config parsing, and the Teams notifier gating.
