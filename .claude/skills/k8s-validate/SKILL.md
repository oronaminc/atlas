---
name: k8s-validate
description: deploy/(k8s 매니페스트, kustomize 오버레이, Flux) 수정 후 렌더링+스키마 검증. deploy/ 아래 yaml을 수정했을 때 항상 사용.
---

# K8s/Flux 매니페스트 검증

클러스터 없이 검증한다. kubectl/kubeconform 바이너리가 없으면 먼저 다운로드:

```bash
cd /tmp
[ -x ./kubectl ] || { curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl" && chmod +x kubectl; }
[ -x ./kubeconform ] || curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz | tar xz
```

렌더링 + 스키마 검증 (Flux CRD 포함):

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

Invalid/Errors가 0이어야 통과.

## 주의

- `deploy/flux/kustomization.yaml`은 kustomize 인덱스, Flux Kustomization CR은
  `flux-kustomization.yaml` — 이름 바꾸지 말 것 (충돌 전례 있음).
- prod overlay의 `newTag` 마커 주석(`# {"$imagepolicy": ...}`)은 Flux image automation
  커밋 지점 — 삭제/이동 금지.
- 이미지 경로 변경 시 base의 `images:` name과 overlay의 name이 일치해야 치환됨.
- secret을 git에 평문으로 추가하지 말 것 (dev overlay의 secretGenerator는 dev 전용 예외).
