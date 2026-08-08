# VPA Recommender

Kubernetes VPA의 CPU·Memory request 추천만 수집한다. 이 디렉터리는 자동
반영 기능을 소유하지 않는다.

## 설치 범위

- VPA v1 CRD와 Recommender `1.7.0`
- Audio 전체 Deployment의 `updateMode: Off` VPA
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

## 클러스터 전체 적용 범위

모든 컨테이너는 FinOps 대시보드의 비용·사용량 모집단이다. VPA 객체는 워크로드
수명주기와 변경 위험에 따라 아래처럼 분리한다.

| Class | VPA | 비용 판정 | 범위와 근거 |
|---|---|---|---|
| A `actionable` | Off 관찰 | 실행 후보 | 장기 실행, controller 소유, GitOps로 request 변경 가능 |
| B `stateful_manual` | Off 관찰 | 잠재 기회만 | StatefulSet 및 데이터 계층. 용량·보존기간·복구 검토 필수 |
| C `type_specific` | 미등록 | 별도 분석 | DaemonSet은 노드별, Job은 실행별 분석 |
| C `critical_system` | 미등록 | 표시만 | Admission·보안·네트워크·스토리지 핵심 경로 |

A에는 업무 Deployment 전체와 Grafana, OpenCost, exporter, dashboard 등 일반
플랫폼 Deployment를 포함한다. B에는 OpenSearch, Harbor DB/Redis 등 직접
관리되는 StatefulSet을 포함하되 실행 가능한 절감액에는 합산하지
않는다. C 제외는 비용을 숨기는 것이 아니라 VPA 단일 추천값이 해당 워크로드의
운영 단위를 대표하지 못하거나 장애 영향이 절감 효과보다 크기 때문이다.

현재 인벤토리는 총 26개다.

- A 22개: Audio 5개, Grafana, OpenCost, kube-state-metrics, FinOps
  Pushgateway, CloudWatch Exporter, OpenSearch Dashboards, Argo CD 일반
  Deployment 6개, Harbor 일반 Deployment 5개
- B 4개: Argo CD Application Controller, OpenSearch, Harbor Database,
  Harbor Redis
- C: node-exporter/Fluent Bit/CNI/CSI/ztunnel 같은 DaemonSet, 모든
  Job/CronJob, Kyverno/cert-manager/external-secrets/Istio 같은 보안·Admission
  경로, Metrics Server와 VPA 자체, Operator가 생성해 직접 targetRef로 사용할
  수 없는 Prometheus/Alertmanager StatefulSet

대상 이름과 Class는 `resources/vpa-platform-workloads.yaml`에 선언해 대상
변경과 리뷰 근거가 Git 이력에 남는다.

## 짧은 프로젝트 관찰 기간

Recommender는 checkpoint에 자체 샘플을 보존하고 최신 Metrics API 샘플을 계속
반영한다. VPA 1.7.0의 Prometheus history provider는 metric 이름을 query 설정에
전달하지 않는 결함이 라이브 검증에서 확인되어 사용하지 않는다. 짧은 프로젝트의
운영 보조 근거는 별도 대시보드가 Prometheus 7일 이력의 P95/P99/Max, OOM,
throttling, HPA와 OpenCost allocation을 계속 계산해 제공한다. 이 값들은 request
권고 계산에 사용하지 않으며 VPA 결과의 운영 위험과 비용 맥락만 설명한다.

대시보드의 유일한 권고값은 VPA Recommender의 Target이며 Lower/Upper를 함께
표시한다. `VPA 수동검토`는 VPA 자체 관찰이 6시간 이상이고 OOM·throttling·HPA
guardrail을 통과한 A Class에만 표시한다. 이는 자동 승인이나 request 변경 지시가
아니며, 시간이 누적될수록 다시 검토한다.

- VPA 관찰 `<6h`: 수집 중, 판단 유보
- VPA 관찰 `>=6h`: 제한적인 수동검토 후보
- VPA 관찰 `>=24h`: 단기 추세 재검토
- Prometheus 관찰 시간: VPA 나이를 대체하지 않는 별도 보조 이력

CPU 25m은 VPA 1.7.0 공식 기본 하한이다. Memory 64Mi는 공식 기본값이 아니라
현재 업무 Deployment의 최소 request와 맞춘 프로젝트 정책이다. 추천 전용이며
실제 변경에는 별도 PR과 workload owner 승인이 필요하다.

## 배치와 의존성

Recommender는 `platform=gcp`, `role=monitoring` 노드와 `autoscaling`
네임스페이스에 배치한다. 최신 사용량은 같은 네임스페이스의 Metrics Server가
제공하는 `metrics.k8s.io` API에서 읽는다. Metrics Server에서 kubelet 인증서
검증을 우회하는 `--kubelet-insecure-tls`는 사용하지 않는다.
