#!/usr/bin/env bash
# Local Kubernetes test: build images, load them into a kind cluster, deploy
# the dev overlay, and port-forward the UI.
#
# Prereqs: docker, kind, kubectl
# Usage:   ./deploy/kind-up.sh
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=atlas-dev
BACKEND_IMG=ghcr.io/oronaminc/atlas/backend:dev
FRONTEND_IMG=ghcr.io/oronaminc/atlas/frontend:dev

echo "==> 1/5 kind cluster"
if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER"
fi

echo "==> 2/5 build images"
docker build -t "$BACKEND_IMG" ./backend
docker build -t "$FRONTEND_IMG" ./frontend

echo "==> 3/5 load images into kind"
kind load docker-image "$BACKEND_IMG" --name "$CLUSTER"
kind load docker-image "$FRONTEND_IMG" --name "$CLUSTER"

echo "==> 4/5 deploy (dev overlay, images retagged to :dev)"
kubectl kustomize deploy/k8s/overlays/dev \
  | sed "s|ghcr.io/oronaminc/atlas/backend:latest|$BACKEND_IMG|g; s|ghcr.io/oronaminc/atlas/frontend:latest|$FRONTEND_IMG|g" \
  | kubectl apply -f -

echo "==> 5/5 wait for rollout"
kubectl -n atlas rollout status statefulset/atlas-postgres --timeout=180s
kubectl -n atlas rollout status deploy/atlas-redis --timeout=120s
kubectl -n atlas rollout status deploy/atlas-backend --timeout=300s
kubectl -n atlas rollout status deploy/atlas-frontend --timeout=120s
kubectl -n atlas rollout status deploy/atlas-worker --timeout=120s

echo
echo "Done. Next steps:"
echo "  # 최초 admin 생성"
echo "  kubectl -n atlas exec deploy/atlas-backend -- python scripts/create_admin.py admin@example.com admin <password>"
echo "  # UI 접속 (http://localhost:8080)"
echo "  kubectl -n atlas port-forward svc/atlas-frontend 8080:80"
