# k8s-manifests

클러스터 워크로드의 GitOps 원본이다. Argo CD가 이 저장소를 동기화하며,
일상적인 변경은 `kubectl apply`가 아니라 PR로 반영한다.

## 구조

```text
bootstrap/              Argo CD Root Application 최초 등록 파일
applications/           Root App이 관리하는 운영 Application 목록
governance/             네임스페이스 보안 등급, Kyverno 보안·FinOps 정책과 예외
  namespaces/           네임스페이스와 Pod Security Admission 등급
platform/
  aws/                  AWS 배치 플랫폼 구성
  gcp/                  GCP 배치 플랫폼 구성
  onp/                  On-prem 배치 플랫폼 구성
apps/                   사용자 서비스
```

## Argo CD 배포 구조

Argo CD 설치와 GitHub App repository credential은 별도 bootstrap 절차로
관리한다. 설치가 끝난 뒤 `bootstrap/root-application.yaml`을 한 번 등록하면
Root Application이 `main` 브랜치의 `applications/`만 동기화한다.

```text
bootstrap/root-application.yaml
  -> applications/kustomization.yaml
       -> applications/<part>.yaml
            -> platform/<platform>/<part> 또는 apps/<app>
```

저장소 루트나 `platform/` 전체를 재귀적으로 적용하지 않는다. 따라서
`platform/onp/argocd/`의 Argo CD 설치 매니페스트는 Root Application에 의해
재설치되지 않는다.

새 파트는 자신의 매니페스트 경로를 완성한 뒤 `applications/`에 운영
Application을 추가하고 `applications/kustomization.yaml`에 명시적으로
등록한다. Root App은 `main`만 감시하므로 feature branch가 자동으로 운영
클러스터에 배포되지는 않는다. 자세한 최초 등록 및 브랜치 규칙은
`bootstrap/README.md`를 참고한다.

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
`platform/gcp/kube-prometheus-stack/`에서 하나의 Helm release로 관리한다.
OpenCost는 별도 release로 두되 같은 Prometheus를 데이터 원본으로 사용한다.

## 거버넌스

집행 주체가 둘이다. 파드 하드닝 기본선은 Kubernetes 내장 **Pod Security
Admission** 이 `governance/namespaces/` 의 네임스페이스 라벨로 걸고,
그 밖의 전부는 **Kyverno** 가 맡는다. 나눈 이유는 `governance/README.md`.

`governance/secops/`와 `governance/finops/`는 공통 강제 정책,
`governance/exceptions/`는 승인된 임시 예외다. 예외에는 사유·승인자·
재검토일을 기록한다.

**적용 순서가 있다.** `governance/` 가 `platform/`·`apps/` 보다 먼저다.
네임스페이스가 없으면 그 안에 넣는 자원이 전부 실패하고, PSA 라벨은
파드가 뜬 뒤에 붙이면 그 파드에는 적용되지 않는다.

클라우드 태그·IAM·보안그룹은 이 저장소가 아니라
[`01-infra-provisioning`](../01-infra-provisioning/)에서 관리한다.
