# k8s-manifests

클러스터 워크로드의 GitOps 원본이다. Argo CD가 이 저장소를 동기화하며,
일상적인 변경은 `kubectl apply`가 아니라 PR로 반영한다.

## 구조

```text
governance/             Kyverno 보안·FinOps 정책과 예외
platform/
  aws/                  AWS 배치 플랫폼 구성
  gcp/                  GCP 배치 플랫폼 구성
  onp/                  On-prem 배치 플랫폼 구성
apps/                   사용자 서비스
```

## 라벨과 배치

기준 문서는
[`00-cantaloupe-resources/k8s-labeling-convention.md`](../00-cantaloupe-resources/k8s-labeling-convention.md)다.

- 일반 Pod template: `app`, `area`, `platform`
- 여러 플랫폼에 뜨는 DaemonSet: `app`, `area`
- Node: `platform=aws|gcp|onp`, `role=<역할>`
- 팀 워크로드는 `default` Namespace를 사용하지 않는다.

직접 작성한 매니페스트의 `nodeSelector`는 플랫폼 Kustomization에서 공통
주입한다. Helm chart는 각 `values.yaml`에서 설정한다.

| 위치 | 배치 |
|---|---|
| `apps/audio/`, `platform/aws/` | `platform=aws`, `role=service` |
| `platform/gcp/kube-prometheus-stack/`, `opencost/` | `platform=gcp`, `role=monitoring` |
| `platform/onp/` | `platform=onp`, `role=devops` |

Kafka 등 배치가 확정되지 않은 구성요소는 임의로 특정 플랫폼에 넣지 않는다.

## 모니터링

Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics는
향후 `platform/gcp/kube-prometheus-stack/`에서 하나의 Helm release로
관리한다. OpenCost는 별도 release로 두되 같은 Prometheus를 데이터 원본으로
사용한다. 현재 두 디렉터리는 구현 전 빈 골격이며 Argo CD 동기화 대상이 아니다.

## 거버넌스

`governance/secops/`와 `governance/finops/`는 공통 강제 정책,
`governance/exceptions/`는 승인된 임시 예외다. 예외에는 사유·승인자·
재검토일을 기록한다.

클라우드 태그·IAM·보안그룹은 이 저장소가 아니라
[`01-infra-provisioning`](../01-infra-provisioning/)에서 관리한다.
