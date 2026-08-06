# FinOps Right-sizing Demo

This is an isolated presentation experiment. It does not process production
audio and it does not claim immediate VM-bill savings.

## Run

```bash
kubectl apply -k experiments/finops-rightsizing-demo
kubectl -n finops-demo rollout status deployment/finops-demo-before
kubectl -n finops-demo rollout status deployment/finops-demo-after
```

Wait at least two OpenCost/Prometheus evaluation cycles (about 2–3 minutes),
then open `Cantaloupe FinOps — Right-sizing Demo` in Grafana.

## Verify

```bash
kubectl -n finops-demo get deploy,pod -o wide
kubectl -n finops-demo get deploy \
  -o custom-columns='NAME:.metadata.name,CPU:.spec.template.spec.containers[0].resources.requests.cpu,MEMORY:.spec.template.spec.containers[0].resources.requests.memory'
```

Expected comparison:

| Workload | CPU Request | Memory Request |
|---|---:|---:|
| finops-demo-before | 800m | 512Mi |
| finops-demo-after | 100m | 128Mi |

## Cleanup

```bash
kubectl delete -k experiments/finops-rightsizing-demo
```

The deletion is recoverable by applying the kustomization again. The demo has
no PVC or business data.
