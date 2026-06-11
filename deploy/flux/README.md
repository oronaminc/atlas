# Flux CD 구성

이 디렉터리의 매니페스트는 **flux-system namespace에 적용**한다 (Flux v2가 이미
부트스트랩되어 있다고 가정). 적용 전에 두 가지를 준비:

```bash
# 1) Flux가 이 repo를 읽을 자격증명 (GitLab deploy token 권장, read_repository)
flux create secret git atlas-repo-auth \
  --url=https://gitlab.internal/platform/atlas \
  --username=<deploy-token-user> --password=<deploy-token>

# 2) 이미지 자동 업데이트가 커밋을 push할 자격증명 (write_repository)
#    atlas-repo-auth 토큰에 write 권한을 주거나 별도 secret 사용

# 적용
kubectl apply -k deploy/flux
```

흐름:

```
GitLab CI (test → kaniko build → registry push, 태그 main-<iid>-<sha>)
   ↓
ImageRepository가 레지스트리 폴링 → ImagePolicy가 iid 최댓값 선택
   ↓
ImageUpdateAutomation이 deploy/k8s/overlays/prod/kustomization.yaml 의
마커(# {"$imagepolicy": ...}) 위치에 새 태그를 커밋
   ↓
GitRepository가 커밋 감지 → Kustomization이 prod 오버레이 reconcile
```

이미지 자동 배포를 원하지 않으면 image-automation.yaml을 빼고
prod overlay의 newTag를 수동으로 올리면 된다.

**secret 주의**: `atlas-secrets`는 git에 평문으로 두지 말 것. 운영에서는
SOPS(+age) 또는 SealedSecrets로 암호화해 repo에 넣고 Flux가 복호화하게
하거나, 최소한 클러스터에 수동 생성(`deploy/k8s/base/secret.example.yaml` 참고).
