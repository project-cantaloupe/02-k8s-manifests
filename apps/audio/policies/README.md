# Audio Security Policies

## Public Access Boundary

`public-access-ingress.yaml`은 `audio-ingress` Gateway에서 공개 `GET`·`HEAD`,
Preflight `OPTIONS`, 그리고 Public Upload에 필요한 두 POST만 허용한다.

- `POST /v1/audios/uploads`
- `POST /v1/audios/{audio-id}/complete`

API는 익명 요청에서 `visibility=public`만 허용하고 파일당 25 MiB, API replica당
분당 5개 세션으로 제한한다. 완료 요청은 세션 생성 시 발급된 Upload ID를
`X-Cantaloupe-Upload-Token`으로 다시 제시해야 한다. Private Upload, Visibility
PATCH 등 다른 쓰기 경로는 계속 인증이 필요하며 Gateway에서도 허용하지 않는다.

현재 API의 `AUTH_MODE=oidc`는 Token 없는 Public 요청만 선택적으로 통과시키고 잘못된
Token은 `401`로 거부한다. 인증 필수 Endpoint는 유효한 OIDC Subject가 없으면 닫힌다.
Gateway 정책은 공개 진입점의 1차 경계이고, API의 Public Upload 검증과 Authenticator는
우회 경로에도 유지되는 최종 경계다.

## IMDS Egress

AWS Service Node에 Instance Profile을 연결하면 같은 Node의 Pod가 EC2 Metadata
Service를 통해 Node Role 자격 증명을 요청할 수 있다. Pod별 IAM을 사용할 수 없는
동안 Node 단위 권한의 노출 범위를 줄이기 위해 `audio-web`의 IMDS 접근을 차단한다.

`audio-web`은 정적 Web 요청을 처리하며 AWS API를 호출하지 않는다. 정책은 일반
IPv4 Egress를 유지하고 `169.254.169.254/32`만 제외하므로 DNS, 내부 Service와 외부
API 통신을 별도로 제한하지 않는다.

`audio-api`, `audio-events`, `audio-transcode`는 Node Instance Profile을 사용하는
동안 이 정책의 선택 대상이 아니다. 이는 임시 운영 경계이며 Service Account OIDC와
Pod별 IAM을 사용할 수 있게 되면 Node Role 의존성을 제거한다.

`app-audio` Application은 Root Application에 등록되어 있어 `main` 병합 뒤 Argo CD가
자동으로 동기화한다.

## 검증

```bash
kubectl kustomize apps/audio
```

배포 뒤 `audio-web` Pod에서 IMDS 차단과 일반 Egress를 각각 확인한다.

```bash
kubectl -n apps exec deploy/audio-web -- \
  wget -T 2 -qO- http://169.254.169.254/latest/meta-data/

kubectl -n apps exec deploy/audio-web -- \
  wget -T 5 -qO- https://example.com >/dev/null
```
