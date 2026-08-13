#!/usr/bin/env bash
set -euo pipefail

fixture="$(mktemp)"
trap 'rm -f "$fixture"' EXIT
cat >"$fixture" <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: finops-policy-negative-test
  namespace: apps
spec:
  containers:
    - name: missing-resources
      image: registry.k8s.io/pause:3.10
YAML

if kyverno apply governance/finops/require-resource-limits.yaml --resource "$fixture"; then
  echo "ERROR: Kyverno accepted the intentional resource-policy violation" >&2
  exit 1
fi

echo "Kyverno rejected the intentional resource-policy violation as expected"
