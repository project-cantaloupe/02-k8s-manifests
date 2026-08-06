# Audio Workload

AWS Service Worker에서 실행하는 Audio 서비스 매니페스트다. `nodeSelector`는
`kustomization.yaml`이 모든 Deployment에 일괄 주입하므로 개별 매니페스트에 적지
않는다.

## 구성

`apps` Namespace는 여기 없다. governance가 소유한다 →
`governance/namespaces/apps.yaml`. Namespace는 오래 살고 Pod Security Admission
등급이 붙는 자리라, 앱 갈래마다 흩어 두면 어느 쪽이 이기는지가 배포 순서에
달리게 된다.

```text
gateway.yaml          audio-ingress Namespace의 Gateway 진입점
settings.yaml         세 워크로드가 공유하는 비민감 ConfigMap
virtual-service.yaml  경로 분기를 한 곳에서 관리 (/v1 -> api, 나머지 -> web)
policies/             IMDS Egress 제한 등 보안 정책
web/                  audio-web
api/                  audio-api와 audio-events (같은 Image의 다른 진입점)
worker/               audio-transcode
```

### Mesh 참여 기준 — ambient

**Sidecar를 쓰지 않는다.** Namespace의 `istio.io/dataplane-mode: ambient`가
`apps`의 모든 Pod를 노드별 ztunnel 프록시에 태운다. Pod에 아무 라벨도 필요 없다.

`apps`가 PSA `restricted`이기 때문이다. Sidecar 주입기는 `istio-init` init
컨테이너를 넣고 그것이 iptables를 고치려고 `NET_ADMIN`·`NET_RAW`를 요구하는데,
`restricted`는 모든 capability를 drop하므로 어드미션이 Pod를 거부한다. ambient는
그 특권을 노드 DaemonSet(`istio-cni`·`ztunnel` Namespace)으로 내린다.

**빼는 쪽을 명시한다.** Sidecar 때와 정반대다.

| 워크로드 | Mesh | 이유 |
| --- | --- | --- |
| `audio-web` | O | Gateway에서 오는 트래픽 수신 |
| `audio-api` | O | Gateway에서 오는 트래픽 수신 |
| `audio-events` | O | Namespace 기본값. 빼도 이득이 없어 그대로 둔다 |
| `audio-transcode` | X | Pod 라벨 `istio.io/dataplane-mode: none`. S3·SQS만 쓰고, 트랙당 처리 비용에 Mesh 비용을 섞지 않는다 |

⚠️ **ztunnel은 L4까지만 집행한다.** HTTP 메서드·경로 조건이 붙은
AuthorizationPolicy나 DestinationRule의 트래픽 정책은 waypoint 프록시를 세우기
전까지 **에러 없이 무시된다.**

`istio-injection` 라벨은 Namespace에 두지 않는다. ambient에서는 주입기를 안 쓰니
무해해 보이지만, 값이 `disabled`면 Webhook이 그 Namespace를 대상에서 제외해
나중에 Pod 단위 지정으로 되돌리려 해도 무시된다. "끄는 것"과 "두지 않는 것"이
다르다.

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

### 2. `audio-database` — DATABASE_URL

RDS가 `manage_master_user_password`로 관리하는 Secret에서 비밀번호를 읽어 만든다.

**Control Plane Node에서 실행한다.** Instance Profile로 이 Secret을 읽을 권한이
있다. 비밀번호가 화면이나 셸 히스토리에 남지 않도록 한 파이프라인으로 처리한다.

```bash
DB_SECRET=$(aws secretsmanager get-secret-value \
  --secret-id "$(aws rds describe-db-instances --db-instance-identifier cntlp-aws-api-db \
    --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)" \
  --query SecretString --output text)

DB_HOST=$(aws rds describe-db-instances --db-instance-identifier cntlp-aws-api-db \
  --query 'DBInstances[0].Endpoint.Address' --output text)

kubectl -n apps create secret generic audio-database \
  --from-literal=DATABASE_URL="postgres://cntlpadmin:$(printf '%s' "$DB_SECRET" | jq -r .password)@$DB_HOST:5432/audio?sslmode=require"

unset DB_SECRET
```

### 3. `cloudfront-signing-key` — CloudFront 서명 개인키

**개인키는 Control Plane Node에서 만들고 그 노드 밖으로 내보내지 않는다.**
공개키만 Terraform에 전달한다. 노트북에서 키를 만들면 개인키가 AWS 밖에 존재하게
된다.

Control Plane Node에서 키 쌍을 만든다.

**개인키는 PKCS#1 형식이어야 한다.** `audio-api`가 쓰는 AWS SDK의
`cloudfrontsign.LoadPEMPrivKeyFile`이 `x509.ParsePKCS1PrivateKey`를 사용하므로
PKCS#8을 넣으면 기동 시 실패한다.

```text
load CloudFront private key: x509: failed to parse private key
(use ParsePKCS8PrivateKey instead for this key format)
```

`openssl genpkey`는 PKCS#8(`BEGIN PRIVATE KEY`)을 만든다. 변환이 필요하다.

```bash
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -out /tmp/cloudfront-pkcs8.pem
openssl rsa -traditional -in /tmp/cloudfront-pkcs8.pem \
  -out /tmp/cloudfront-private-key.pem
openssl pkey -in /tmp/cloudfront-private-key.pem -pubout \
  -out /tmp/cloudfront-public-key.pub
```

첫 줄이 `-----BEGIN RSA PRIVATE KEY-----`인지 확인한다.

```bash
head -1 /tmp/cloudfront-private-key.pem
```

형식만 바뀌고 키 자체는 같으므로 공개키도 동일하다. 이미 등록된 키를 변환하는
경우 CloudFront를 다시 적용할 필요가 없다.

같은 노드에서 바로 Kubernetes Secret을 만든다.

```bash
kubectl -n apps create secret generic cloudfront-signing-key \
  --from-file=cloudfront-private-key.pem=/tmp/cloudfront-private-key.pem
```

공개키만 가져가 Terraform에 반영한다. 공개 값이므로 이동해도 무방하다.

```bash
# 작업 머신에서
scp ubuntu@cntlp-aws-cp-01:/tmp/cloudfront-public-key.pub \
  01-infra-provisioning/terraform/aws/audio/cloudfront-public-key.pub
```

Terraform이 CloudFront 공개키와 Key Group을 갱신한다. Distribution 전파에 보통
5~15분 걸린다.

```bash
cd 01-infra-provisioning
AWS_PROFILE=cntlp terraform -chdir=terraform/aws/audio apply
```

반영이 끝나면 노드의 개인키 파일을 지운다. Kubernetes Secret에만 남는다.

```bash
shred -u /tmp/cloudfront-pkcs8.pem /tmp/cloudfront-private-key.pem \
  /tmp/cloudfront-public-key.pub
```

> 조직 표준 시크릿 저장소는 HashiCorp Vault다. 구축 중이라 이번에는 Kubernetes
> Secret에 직접 둔다. Deployment는 Secret 이름만 참조하므로 Vault 연동 시
> External Secrets Operator의 ExternalSecret으로 교체하면 매니페스트 변경이
> 필요 없다.

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
