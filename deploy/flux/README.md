# Flux CD setup

The manifests in this directory are **applied to the flux-system namespace** (assumes
Flux v2 is already bootstrapped). Prepare two things before applying:

```bash
# 1) Credentials for Flux to read this repo (GitLab deploy token recommended, read_repository)
flux create secret git atlas-repo-auth \
  --url=https://gitlab.internal/platform/atlas \
  --username=<deploy-token-user> --password=<deploy-token>

# 2) Credentials for image automation to push commits (write_repository)
#    Either grant write to the atlas-repo-auth token or use a separate secret

# Apply
kubectl apply -k deploy/flux
```

Flow:

```
GitLab CI (test → kaniko build → registry push, tags main-<iid>-<sha>)
   ↓
ImageRepository polls the registry → ImagePolicy picks the highest iid
   ↓
ImageUpdateAutomation commits the new tag to the marker comments
(# {"$imagepolicy": ...}) in deploy/k8s/overlays/prod/kustomization.yaml
   ↓
GitRepository detects the commit → Kustomization reconciles the prod overlay
```

If you don't want automatic image deployment, drop image-automation.yaml and
bump newTag in the prod overlay manually.

**Secret warning**: never keep `atlas-secrets` in git as plaintext. In production,
encrypt with SOPS(+age) or SealedSecrets and let Flux decrypt, or at minimum create
it manually in-cluster (see `deploy/k8s/base/secret.example.yaml`).
