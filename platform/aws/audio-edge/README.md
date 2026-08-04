# AWS Audio Edge

AWS service Worker에서 실행하는 Istio ingress gateway와 독립 Echo 검증 경로다.
실제 `audio-web`, `audio-api` 이미지가 없어도 NLB부터 Service Mesh까지 먼저
검증할 수 있다.

## 기본 경로

```text
NLB TCP 80
  -> Worker 30080
  -> istio-ingress
  -> mesh-smoke
```

NLB health check는 Worker `32021/healthz/ready`를 사용한다. TCP 443은
Production TLS overlay가 활성화된 뒤 Istio Gateway에서 종료한다.

## 준비된 Application 정의

- `istio-base` 1.30.3
- `istiod` 1.30.3
- `istio-ingress` 1.30.3
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

### 3. Istio Ingress Gateway

Istiod와 Sidecar Injector가 준비된 뒤 `istio-ingress.yaml`을 추가하고 병합한다.

```bash
kubectl -n istio-ingress rollout status deployment/istio-ingress --timeout=5m
kubectl -n istio-ingress get service istio-ingress
```

Service의 NodePort가 HTTP `30080`, HTTPS `30443`, Health `32021`인지 확인한다.

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
2. kube-apiserver Service Account Issuer와 JWKS 외부 게시
3. AWS IAM OIDC Provider 등록
4. Terraform Edge의 `enable_cert_manager_iam = true` 적용
5. `applications/cert-manager.yaml`의 IAM Role ARN 교체와 Root 목록 등록
6. `overlays/production/settings.yaml`의 도메인, 이메일, Hosted Zone ID 교체
7. `audio-edge-smoke` Application 경로를 `overlays/production`으로 변경

OIDC 준비 전에는 cert-manager Application과 Production overlay를 등록하지
않는다. Worker Instance Profile 공유와 장기 AWS Access Key 저장은 사용하지 않는다.

## 정적 렌더링

```bash
kubectl kustomize platform/aws/audio-edge/base
kubectl kustomize platform/aws/audio-edge/overlays/production
kubectl kustomize applications
```
