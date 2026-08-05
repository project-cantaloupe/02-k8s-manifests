# Audio IMDS Egress Policy

AWS Service Node에 Instance Profile을 연결하면 같은 Node의 Pod가 EC2 Metadata
Service를 통해 Node Role 자격 증명을 요청할 수 있다. Pod별 IAM을 사용할 수 없는
동안 Node 단위 권한의 노출 범위를 줄이기 위해 `audio-web`의 IMDS 접근을 차단한다.

`audio-web`은 정적 Web 요청을 처리하며 AWS API를 호출하지 않는다. 정책은 일반
IPv4 Egress를 유지하고 `169.254.169.254/32`만 제외하므로 DNS, 내부 Service와 외부
API 통신을 별도로 제한하지 않는다.

`audio-api`, `audio-events`, `audio-transcode`는 Node Instance Profile을 사용하는
동안 이 정책의 선택 대상이 아니다. 이는 임시 운영 경계이며 Service Account OIDC와
Pod별 IAM을 사용할 수 있게 되면 Node Role 의존성을 제거한다.

현재 `apps/audio` Application과 Workload는 Root Application에 등록되지 않았다.
따라서 이 파일의 병합만으로 실행 중인 클러스터 상태는 바뀌지 않는다.

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
