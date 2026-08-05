# AWS Audio Edge

AWS service Worker에서 실행하는 Istio ingress gateway와 독립 Echo 검증 경로다.
실제 `audio-web`, `audio-api` 이미지가 없어도 NLB부터 Service Mesh까지 먼저
검증할 수 있다.

## 기본 경로

```text
NLB TCP 80
  -> AWS Worker 30080
  -> audio-ingress
  -> mesh-smoke
```

NLB health check는 AWS Worker `32021/healthz/ready`를 사용한다. TCP 443은
Production TLS overlay가 활성화된 뒤 Istio Gateway에서 종료한다.

## Gateway 구성

Cluster에 Ingress Gateway는 `audio-ingress` 하나다.

| Gateway | Node | Namespace | NodePort (HTTP/HTTPS/Health) |
| --- | --- | --- | --- |
| `audio-ingress` | `platform=aws`, `role=service` | `audio-ingress` | 30080 / 30443 / 32021 |

이전에는 `istio-ingress`가 On-Prem DevOps Node에서 Argo CD·Jenkins·Harbor를 경로로
노출했다. 그 구성은 Argo CD가 Istio를 배포하면서 Istio가 Argo CD 접근을 통제하는
순환 의존을 만들었고, NLB가 AWS Service Worker NodePort를 Target으로 하는데 Gateway
Pod는 On-Prem에 있어 Target Health가 성립하지 않았다. DevOps 도구를 Tailscale과
각자의 NodePort로 직접 접근하도록 옮기고 On-Prem Istio를 제거했다.

`externalTrafficPolicy: Local`이므로 Gateway Pod가 없는 Node는 응답하지 않는다.
NLB Target은 반드시 AWS Service Worker여야 한다.

NodePort는 Cluster 전역에서 유일하다. `terraform/aws/edge`의
`audio_ingress_*_node_port` 변수도 위 값과 일치시킨다.

## 준비된 Application 정의

- `istio-base` 1.30.3
- `istiod` 1.30.3 (AWS Control Plane Node에서 실행)
- `audio-ingress` 1.30.3 (AWS Audio 전용)
- `audio-edge-smoke`

현재 네 Application은 Root 목록에 등록하지 않는다. 정의 파일과 매니페스트를
먼저 병합한 뒤 아래 순서로 하나씩 활성화한다.

## 단계별 활성화

### 1. Istio Base

`applications/kustomization.yaml`에 `istio-base.yaml`을 추가하고 병합한다.

```bash
kubectl -n devops get application istio-base
kubectl get crd gateways.networking.istio.io
kubectl get crd virtualservices.networking.istio.io
```

Base chart가 생성하는 `istiod-default-validator`는 다음 단계에서 생성할
`istio-system/istiod` Service를 참조한다. 따라서 Base만 설치된 동안
Application Health가 `Degraded`로 표시될 수 있다. 동기화 작업 성공과 필수 CRD의
`Established` 상태를 Base 단계 완료 조건으로 사용한다.

### 2. Istiod

Base CRD가 확인된 뒤 `istiod.yaml`을 추가하고 병합한다.

```bash
kubectl -n istio-system rollout status deployment/istiod --timeout=5m
kubectl get mutatingwebhookconfiguration istio-sidecar-injector
```

Istiod는 webhook endpoint 준비 후 `caBundle`과 validator의 `failurePolicy`를
런타임에 갱신한다. `istio-base`와 `istiod` Application은 해당 webhook 이름과
필드만 `ignoreDifferences`로 제외하고 `RespectIgnoreDifferences=true`로 동기화
중에도 런타임 값을 보존한다.

### 3. AWS Audio Ingress Gateway

Istiod와 Sidecar Injector가 준비된 뒤 `audio-ingress.yaml`을 추가하고 병합한다.

```bash
kubectl -n audio-ingress rollout status deployment/audio-ingress --timeout=5m
kubectl -n audio-ingress get service audio-ingress
kubectl -n audio-ingress get pod -o wide
```

Service의 NodePort가 HTTP `30080`, HTTPS `30443`, Health `32021`인지, Pod가
AWS Service Worker Node에 배치됐는지 확인한다. `externalTrafficPolicy: Local`
이므로 Pod가 AWS Worker에 없으면 NLB Target Health가 실패한다.

### 4. Audio Edge Smoke

Ingress Gateway가 준비된 뒤 `audio-edge-smoke.yaml`을 추가하고 병합한다.

```bash
kubectl -n apps rollout status deployment/mesh-smoke --timeout=5m
kubectl -n apps get pod -l app=mesh-smoke \
  -o custom-columns='NAME:.metadata.name,CONTAINERS:.spec.containers[*].name'
```

각 Pod의 container 목록에 `echo`와 `istio-proxy`가 함께 있어야 한다.

현재 검증 범위는 단일 Backend HTTP routing과 mTLS다. Canary subset과 가중치
분배는 애플리케이션 버전 전환을 시험할 때 별도 변경으로 추가한다.

모든 구성은 AWS `platform=aws`, `role=service` Node에 배치한다. `apps`
Namespace 전체에는 sidecar를 자동 주입하지 않고 검증 workload에만 명시적으로
주입한다.

## Production TLS 활성화 조건

1. Route53 Public Hosted Zone과 `publicHost` 확정
2. cert-manager의 Route53 DNS-01 자격증명 방식 결정
3. Terraform Edge의 `enable_cert_manager_iam = true` 적용
4. `overlays/production/settings.yaml`의 도메인, 이메일, Hosted Zone ID 교체
5. `audio-edge-smoke` Application 경로를 `overlays/production`으로 변경

2번은 아직 결정되지 않았다. 이 PoC는 Workload IAM(OIDC)을 채택하지 않고 AWS
Service Worker의 Node Instance Profile을 사용하기로 했는데, cert-manager도 같은
Node에 배치되므로 Route53 권한을 Node Role에 추가하면 Node 권한이 더 넓어진다.
Audio 전용 권한과 분리할지 별도로 판단한다.

장기 AWS Access Key 저장은 어떤 경우에도 사용하지 않는다.

> Node Instance Profile은 ServiceAccount 단위가 아니라 Node 단위 권한이다.
> Calico GlobalNetworkPolicy로 IMDS 접근을 제한하지만 Pod별 IAM 격리를 완전히
> 대체하지는 않는다. 운영 환경에서는 OIDC 기반 Workload IAM으로 전환한다.

## 정적 렌더링

```bash
kubectl kustomize platform/aws/audio-edge/base
kubectl kustomize platform/aws/audio-edge/overlays/production
kubectl kustomize applications
```
