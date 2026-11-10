#!/usr/bin/env bash
# Spin up a throwaway local Kubernetes cluster (kind), build the app image,
# load it in, and install this chart — for testing the chart itself, not
# for anything real. Requires: docker, kind, kubectl, helm.
#
# Usage: deploy/helm/promhis/hack/kind-up.sh
# Then:  kubectl --context kind-promhis-test port-forward svc/promhis 18000:8000
#        open http://localhost:18000  (login: admin / kindtestpass)
# Teardown: deploy/helm/promhis/hack/kind-down.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../../.."  # repo root
chart_dir="deploy/helm/promhis"

if ! kind get clusters 2>/dev/null | grep -qx promhis-test; then
  kind create cluster --name promhis-test
fi

docker build -t promhis:kind-test .
kind load docker-image promhis:kind-test --name promhis-test

helm upgrade --install promhis "$chart_dir" \
  -f "$chart_dir/hack/test-values.yaml" \
  --kube-context kind-promhis-test

kubectl --context kind-promhis-test rollout status deployment/promhis --timeout=120s
kubectl --context kind-promhis-test rollout status deployment/promhis-postgres --timeout=120s

echo
echo "Ready. In another terminal:"
echo "  kubectl --context kind-promhis-test port-forward svc/promhis 18000:8000"
echo "  open http://localhost:18000   (login: admin / kindtestpass)"
