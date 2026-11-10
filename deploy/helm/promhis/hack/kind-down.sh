#!/usr/bin/env bash
# Tear down everything kind-up.sh created.
set -euo pipefail

helm uninstall promhis --kube-context kind-promhis-test 2>/dev/null || true
kind delete cluster --name promhis-test
docker rmi promhis:kind-test 2>/dev/null || true
