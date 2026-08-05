# Audio Workload

AWS Service Worker에서 실행하는 Audio 서비스 매니페스트다. `nodeSelector`는
`kustomization.yaml`이 모든 Deployment에 일괄 주입하므로 개별 매니페스트에 적지
않는다.

## 구성

```text
namespace.yaml        apps Namespace 소유. istio-injection 라벨을 두지 않는다
gateway.yaml          audio-ingress Namespace의 Gateway 진입점
settings.yaml         세 워크로드가 공유하는 비민감 ConfigMap
virtual-service.yaml  경로 분기를 한 곳에서 관리 (/v1 -> api, 나머지 -> web)
policies/             IMDS Egress 제한 등 보안 정책
web/                  audio-web
api/                  audio-api와 audio-events (같은 Image의 다른 진입점)
worker/               audio-transcode
```

### Sidecar 주입 기준

Namespace 전체 자동 주입은 켜지 않는다. Mesh 안에서 들어오는 트래픽을 받는
워크로드만 Pod 라벨로 명시한다.

| 워크로드 | Sidecar | 이유 |
| --- | --- | --- |
| `audio-web` | O | Gateway에서 오는 트래픽 수신 |
| `audio-api` | O | Gateway에서 오는 트래픽 수신 |
| `audio-events` | X | SQS와 RDS만 사용. Mesh 인바운드 없음 |
| `audio-transcode` | X | S3와 SQS만 사용. 트랙당 처리 비용에 Mesh 비용을 섞지 않는다 |

`istio-injection` 라벨을 Namespace에 두면 안 된다. 값이 `disabled`면 Webhook이
그 Namespace를 대상에서 제외해 Pod 단위 지정도 무시된다.

## 클러스터에서 직접 만들어야 하는 것

Git에 넣을 수 없는 값들이다. 클러스터를 다시 만들면 이 단계도 다시 해야 한다.

장기적으로는 External Secrets Operator로 Secrets Manager에서 동기화하는 방향이
맞다. 지금은 임시 조치다.

### 1. `ghcr-pull` — 이미지 Pull Secret

GHCR 패키지가 private이므로 필요하다. `read:packages` 권한 Token이면 충분하다.

```bash
kubectl -n apps create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<read-packages-token>
```

### 2. `audio-aws-endpoints` — SQS Queue URL

Queue URL에 AWS 계정 ID가 들어가므로 커밋하지 않는다. Terraform 출력에서 만든다.

```bash
cd 01-infra-provisioning/terraform/aws/audio
export AWS_PROFILE=cntlp

kubectl -n apps create configmap audio-aws-endpoints \
  --from-literal=SCAN_RESULT_QUEUE_URL="$(terraform output -json queue_urls | jq -r .scan_result)" \
  --from-literal=TRANSCODE_QUEUE_URL="$(terraform output -json queue_urls | jq -r .transcode)" \
  --from-literal=TRANSCODE_RESULT_QUEUE_URL="$(terraform output -json queue_urls | jq -r .transcode_result)" \
  --from-literal=CLOUDFRONT_BASE_URL="$(terraform output -raw cloudfront_base_url)" \
  --from-literal=CLOUDFRONT_KEY_PAIR_ID="$(terraform output -raw cloudfront_key_pair_id)"
```

### 3. `audio-database` — DATABASE_URL

RDS가 `manage_master_user_password`로 관리하는 Secret에서 비밀번호를 읽어 만든다.
비밀번호를 셸 히스토리에 남기지 않도록 한 줄로 처리한다.

```bash
cd 01-infra-provisioning/terraform/aws/database
export AWS_PROFILE=cntlp

SECRET_ARN=$(terraform output -raw master_user_secret_arn)
HOST=$(terraform output -raw database_address)
PORT=$(terraform output -raw database_port)
DBNAME=$(terraform output -raw database_name)
USER=$(terraform output -raw master_username)

kubectl -n apps create secret generic audio-database \
  --from-literal=DATABASE_URL="postgres://$USER:$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ARN" --query SecretString --output text | jq -r .password)@$HOST:$PORT/$DBNAME?sslmode=require"
```

### 4. `cloudfront-signing-key` — CloudFront 서명 개인키

Signed URL 발급에 필요하다. 개인키를 Git이나 로그에 남기지 않는다.

```bash
kubectl -n apps create secret generic cloudfront-signing-key \
  --from-file=cloudfront-private-key.pem=01-infra-provisioning/terraform/aws/audio/cloudfront-private-key.pem
```

## 데이터베이스 마이그레이션

`03-app-audio/services/api/migrations/001_init.sql`을 RDS에 적용해야 한다. RDS가
Private Subnet에 있으므로 클러스터 안에서 실행한다.

```bash
kubectl -n apps run psql-migrate --rm -it --restart=Never \
  --image=postgres:18-alpine \
  --overrides='{"spec":{"nodeSelector":{"platform":"aws","role":"service"}}}' \
  --env="PGURL=$(kubectl -n apps get secret audio-database -o jsonpath='{.data.DATABASE_URL}' | base64 -d)" \
  -- sh -c 'psql "$PGURL" -f -' < ../03-app-audio/services/api/migrations/001_init.sql
```

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
