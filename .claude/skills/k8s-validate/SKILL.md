---
name: k8s-validate
description: Render+schema-validate after modifying deploy/ (k8s manifests, kustomize overlays, Flux). Always use after changing yaml under deploy/.
---

# K8s/Flux manifest validation

Validates without a cluster. Download binaries first if missing:

```bash
cd /tmp
[ -x ./kubectl ] || { curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl" && chmod +x kubectl; }
[ -x ./kubeconform ] || curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz | tar xz
```

Render + schema validation (includes Flux CRDs):

```bash
cd <repo-root>
/tmp/kubectl kustomize deploy/k8s/base > /tmp/base.yaml
/tmp/kubectl kustomize deploy/k8s/overlays/dev > /tmp/dev.yaml
/tmp/kubectl kustomize deploy/k8s/overlays/prod > /tmp/prod.yaml
/tmp/kubectl kustomize deploy/flux > /tmp/flux.yaml
/tmp/kubeconform -strict -summary \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  /tmp/base.yaml /tmp/dev.yaml /tmp/prod.yaml /tmp/flux.yaml
```

Pass = 0 Invalid / 0 Errors.

## Gotchas

- `deploy/flux/kustomization.yaml` is the kustomize index; the Flux Kustomization CR lives in
  `flux-kustomization.yaml` — do not rename (there was a collision before).
- The `newTag` marker comments (`# {"$imagepolicy": ...}`) in the prod overlay are Flux image
  automation commit points — never delete or move them.
- When changing image paths, the `images:` name in base must match the name in overlays for substitution.
- Never add plaintext secrets to git (the dev overlay secretGenerator is a dev-only exception).
