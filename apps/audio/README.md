# Audio Workload

AWS Service Worker에서 실행하는 Audio 서비스 매니페스트다. `nodeSelector`는
`kustomization.yaml`이 모든 Deployment에 일괄 주입하므로 개별 매니페스트에 적지
않는다.

## 구성

```text
namespace.yaml   apps Namespace 소유. istio-injection은 disabled
gateway.yaml     audio-ingress Namespace의 Gateway 진입점
policies/        IMDS Egress 제한 등 보안 정책
web/             audio-web Deployment, Service, VirtualService
```

`api/`와 `worker/`는 `DATABASE_URL`과 AWS 접근이 준비된 뒤 추가한다.

## 이미지 Pull Secret

컨테이너 이미지는 GHCR의 private 패키지다. GitHub 저장소를 private으로 유지하는
것과 패키지 공개 여부는 별개 설정이지만, 이 프로젝트는 둘 다 private으로 둔다.

Secret은 Token을 담으므로 **Git에 넣지 않는다.** 클러스터에서 직접 만든다.

```bash
kubectl -n apps create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<personal-access-token>
```

Token은 `read:packages` 권한이면 충분하다. Push에 쓰는 `write:packages` Token을
클러스터에 넣지 않는다.

이 수동 단계는 임시 조치다. 장기적으로는 External Secrets Operator로
Secrets Manager에서 동기화하는 방향이 맞다.

Secret이 없으면 Pod가 `ImagePullBackOff` 상태가 된다.

```bash
kubectl -n apps get secret ghcr-pull
kubectl -n apps describe pod -l app=audio-web | tail -20
```

## 이미지 빌드

AWS Node가 모두 x86_64이므로 아키텍처를 명시한다. Apple Silicon에서 그냥
빌드하면 arm64 이미지가 올라가 Pod가 `exec format error`로 기동하지 않는다.

```bash
cd 03-app-audio
docker build --platform linux/amd64 \
  -t ghcr.io/project-cantaloupe/audio-web:dev services/web
docker push ghcr.io/project-cantaloupe/audio-web:dev
```

`VITE_*` 값은 빌드 시점에 박힌다. 런타임 환경변수로 바꿀 수 없다. `audio-api`가
배포된 뒤 `VITE_API_BASE_URL`을 넣어 다시 빌드한다.

## 정적 렌더링

```bash
kubectl kustomize apps/audio
```
