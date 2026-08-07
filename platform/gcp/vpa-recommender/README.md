# VPA Recommender

Kubernetes VPA의 CPU·Memory request 추천만 수집한다. 이 디렉터리는 자동
반영 기능을 소유하지 않는다.

## 설치 범위

- VPA v1 CRD와 Recommender `1.7.0`
- `audio-api`의 `updateMode: Off` VPA
- `RequestsOnly`와 컨테이너별 min/max 경계

다음 구성은 의도적으로 설치하지 않는다.

- VPA Updater
- VPA Admission Controller
- MutatingWebhookConfiguration
- Pod eviction 또는 resize RBAC

`governance/finops/require-vpa-recommendation-only.yaml`이 `Off` 이외의 VPA를
거부한다. 차트 업그레이드 때에는 먼저 렌더링하고 위 네 종류가 생성되지 않는지
확인한다.

## 추천 조회와 반영

```bash
kubectl describe vpa audio-api-recommendation -n apps
kubectl get vpa audio-api-recommendation -n apps \
  -o jsonpath='{.status.recommendation}'
```

VPA `target`을 그대로 적용하지 않는다. 기존 Grafana Right-sizing 후보와 OOM,
throttling, HPA, 대표 부하 구간을 함께 검토하고 Deployment request는 Git PR로만
변경한다.

## 배치와 의존성

Recommender는 `platform=gcp`, `role=monitoring` 노드와 `autoscaling`
네임스페이스에 배치한다. 최신 사용량은 같은 네임스페이스의 Metrics Server가
제공하는 `metrics.k8s.io` API에서 읽는다. Metrics Server에서 kubelet 인증서
검증을 우회하는 `--kubelet-insecure-tls`는 사용하지 않는다.
