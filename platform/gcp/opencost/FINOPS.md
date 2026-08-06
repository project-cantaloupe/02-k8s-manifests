# Cantaloupe OpenCost 가격 모델

## 목적과 범위

이 환경은 AWS, GCP, On-premises의 차이를 비교하기 위해 플랫폼별 가격을 사용한다.
AWS와 GCP는 서울 리전 Linux On-Demand/Regular 공개가격이며, On-premises는
공개가격이 없으므로 팀 TCO 기준을 사용한다. 할인, 크레딧, 세금, 네트워크 및
VM root disk를 포함한 실제 청구액은 아니다.

On-prem 노드는 Microsoft Azure Migrate의 공개 TCO 계산 항목을 참고한 3년
교체원가 방식으로 산정한다. 현재 물리 호스트(6 core/12 thread, 24 GiB)에서
8 vCPU/16 GiB VM이 CPU와 Memory의 66.67%를 예약하므로 같은 비율로 배분한다.
서버 교체원가, 연 10% 유지보수, 전력·PUE 및 Proxmox 인프라 관리비를 포함한
계산값은 `$0.05918/hour`이며 가격표에는 보수적으로 `$0.06/hour`를 적용한다.

이 값은 실제 영수증이 아니라 재현 가능한 replacement-cost benchmark다. 로컬
디스크/PV, 공통 네트워크, 모든 플랫폼에서 발생하는 Kubernetes 운영 인력과
애플리케이션 인력은 노드 Compute 가격에서 제외하여 AWS/GCP 공개 VM 가격과의
비교 범위를 맞춘다. 전력 측정값이나 실제 구매가격이 확보되면 가정값만 교체한다.

운영 가격의 단일 원본은 `pricing-catalog.yaml`이다. 운영자가 새 VM 유형을
도입할 때 `region`, `instanceType`, `purchaseOption`, 시간당 가격과 출처만
검토하여 추가한다. CPU/RAM 배분 기준은 `allocation-policy.yaml`, On-prem 상세
산식은 `TCO-METHODOLOGY.md`에서 별도로 관리한다. 생성 파일인
`generated-values.yaml`과 ConfigMap의 CSV는 직접 수정하지 않는다.

## 노드 총액과 CPU/RAM 배분의 구분

`hourlyPriceUSD`는 플랫폼별 노드 시간당 총액이다. AWS는 EC2 인스턴스 묶음
가격, GCP는 VM 구성 가격, On-premises는 내부 TCO를 사용한다. 반면
`allocation-policy.yaml`의 CPU/RAM 값은 OpenCost가 이 총액을 Workload 자원에
나누기 위한 **배분 가중치**다. 세계 공통 단가나 AWS/On-prem 공식 자원 단가가
아니다. 현재 정책은 공개적으로 CPU와 RAM 구성단가가 분리된 GCP E2 서울 가격
`0.028026/core-hour`, `0.003739/GiB-hour`의 비율을 사용하며 정책 버전을 기록한다.

따라서 플랫폼 비교의 기준값은 `node_total_hourly_cost`이고, CPU/Memory 비용은
동일한 노드 총액 안에서 Right-sizing 기여도를 나눈 추정값으로 해석한다.

## 향후 가격 API 자동화 경계

클라우드별 수집기는 API/공개 가격표 응답을 `pricing-catalog.yaml`의 고정된
`schemaVersion: v1` 형식으로 정규화한다. 생성기만 이 표준 형식을 OpenCost CSV,
checksum과 검증 규칙으로 변환한다. 공급자 응답 필드나 API 버전이 바뀌면 해당
수집기 변환부만 수정하며 OpenCost, Grafana와 경고 구조는 바꾸지 않는다.

자동화 흐름은 `가격 조회 -> v1 정규화 -> 검증 -> 생성 -> 변경폭 검토 -> PR`이다.
클라우드 API가 GitHub에 접근하는 방식이 아니라 GitHub Actions가 읽기 권한으로
가격 API를 조회하고, 검증된 변경만 PR로 제안하도록 구성한다.

가격 카탈로그는 모든 Cloud SKU의 복제본이 아니다. 현재 실행 중인 Node 유형,
Terraform/Karpenter에서 실제 허용한 유형, 적용 승인이 끝난 추천 후보만 포함한다.
GCP Recommender나 AWS Compute Optimizer 후보는 먼저 별도 Recommendation Cache에
저장한다. Provider가 공식 예상 절감액을 제공하면 가격표에 후보를 즉시 추가하지
않고 그 값을 표시한다. 실제 적용을 승인할 때만 공식 가격 Resolver가 해당 후보
하나를 조회하고 가격 PR을 만든다.

따라서 Provider가 새로운 VM 유형을 추천해도 OpenCost 현재 비용 계산은 영향을
받지 않는다. 미등록 유형을 실제 NodePool/Terraform에 허용하려는 변경만 가격표
Coverage 검증을 통과해야 한다.

## On-prem Right-sizing

On-prem은 Provider Recommender가 없으므로 회사 서버 재고와 TCO를 기반으로 자체
추천한다. `onprem-rightsizing-policy.yaml`에는 실제 제공 가능한 Profile, Host
TCO와 안전 여유가 있고, 생성된 Recording Rule은 다음을 계산한다.

- 최근 7일 Node CPU/Memory P95
- P95 30% 여유와 OS/kubelet 예약량을 포함한 필요 용량
- 필요 용량을 만족하는 가장 저렴한 내부 Profile
- 현재 Profile과 권장 Profile의 월 TCO 차이
- 현재 Pod Request가 권장 Profile에 스케줄 가능한지
- 최근 OOMKilled와 Node MemoryPressure 안전 신호

`권장 Profile`과 `즉시 적용 가능`은 다르다. P95 기준으로 축소 가능해도 현재
Request가 들어가지 않으면 Workload Right-sizing을 먼저 수행한다. 모든 추천은
검토·승인 대상이며 VM이나 Workload를 자동 변경하지 않는다.

## Workload 관측 신뢰도

전체 Kubernetes Workload에는 인위적인 부하 테스트를 요구하지 않는다. 현재
Prometheus에 자연스럽게 축적된 데이터로 최대 7일 P95를 계산하고, 확보된 표본
기간을 권장값과 별도로 표시한다.

| 관측 시간 | 분류 | 사용 방법 |
| --- | --- | --- |
| 6시간 미만 | 데이터 부족 | 권장값 적용 금지 |
| 6~24시간 | 초기 후보 | 추가 관측 대상 |
| 24시간~7일 | 검토 가능 | OOM·Request·재스케줄링 확인 후 검토 |
| 7일 이상 | 운영 기준 충족 | 운영 Right-sizing 후보 |

`검토 가능`은 자동 변경 승인이 아니다. 실제 비용 절감은 VM 축소·제거 또는
Karpenter Node 종료가 발생했을 때만 실현된 것으로 구분한다. 통제된 전후 부하
실험은 전체 플랫폼이 아니라 Audio Worker 대시보드에서 별도로 수행한다.

## Provider VM Recommendation Cache

`provider-recommendations.yaml`은 Credential이나 Provider 원본 응답을 저장하지
않고 대시보드에 필요한 비민감 필드만 정규화한다. GCP/AWS CLI 원본 JSON은 로컬
임시파일 또는 Keyless CI Workspace에서만 다루고 Git에 커밋하지 않는다.

추천이 없는 VM은 정상 상태일 수 있으므로 VM별 `추천 없음` 또는 개별 추천의
나이에 대한 Alert는 만들지 않는다. 자동 수집 파이프라인을 운영하게 되면 개별
VM이 아니라 마지막 수집 작업의 성공 여부만 별도로 감시한다.

```bash
# GCP: Workload Identity Federation 또는 사용자 gcloud 인증으로 Snapshot 조회
gcloud recommender recommendations list \
  --recommender=google.compute.instance.MachineTypeRecommender \
  --project="$GCP_PROJECT_ID" \
  --location="$GCP_ZONE" \
  --format=json > /tmp/gcp-recommendations.json

# AWS: Compute Optimizer가 Active여도 분석 중이면 빈 목록이 정상이다.
aws compute-optimizer get-ec2-instance-recommendations \
  --region "$AWS_REGION" > /tmp/aws-recommendations.json

# 비민감 공통 Cache로 정규화
python platform/gcp/opencost/sync_provider_recommendations.py \
  --gcp-json /tmp/gcp-recommendations.json \
  --aws-json /tmp/aws-recommendations.json \
  --aws-status analyzing

# Grafana가 조회할 Recording Rule 생성
python platform/gcp/opencost/generate_provider_recommendations.py
python platform/gcp/opencost/generate_provider_recommendations.py --check
```

운영 자동화는 Scheduled CI가 OIDC/WIF 단기 Token으로 조회하고 변경 PR만 만든다.
장기 GCP Service Account Key나 AWS Access Key를 Kubernetes/GitHub Secret에 넣지
않는다. AWS 분석 결과가 없으면 `analyzing`, 추천이 없으면
`no-active-recommendation` 상태를 유지하며 예상 절감 총액에 포함하지 않는다.

Provider 추천 후보는 OpenCost 가격표와 분리한다. 실제 적용이 승인된 후보만
공식 가격 Resolver를 거쳐 `pricing-catalog.yaml`로 승격하고, Merge 전에 기존
Schema·CSV·Checksum·Coverage 검증을 통과해야 한다.

## 자동 매칭 방식

- OpenCost CSV Provider는 `topology.kubernetes.io/region`과
  `node.kubernetes.io/instance-type`을 결합해 가격을 매칭한다.
- `platform` 라벨은 AWS/GCP/On-prem 구분과 가격 검증에 사용한다.
- 동일한 region과 instance type의 새 노드는 별도 설정 없이 자동으로 가격이 적용된다.
- 새로운 instance type은 가격 누락 경고를 발생시키며, 카탈로그 검토 후 추가한다.
- kubeadm 노드에는 `platform`, `role`, `topology.kubernetes.io/region`,
  `node.kubernetes.io/instance-type` 라벨을 노드 온보딩 과정에서 명시해야 하며,
  Ready 이후 5분 내 누락 경고가 발생한다.
- 서로 다른 플랫폼이 같은 instance type 이름을 사용하게 되면 현재 매칭 키가
  모호해지므로 전용 pricing-key 라벨 방식으로 전환한다.

## 가격 변경 절차

```bash
# 1. pricing-catalog.yaml의 기준 가격·출처·적용일을 검토하고 수정
#    새 On-prem TCO라면 TCO-METHODOLOGY.md의 산식도 함께 갱신
#    CPU/RAM 배분 방식을 바꿀 때만 allocation-policy.yaml 수정
# 2. CSV, checksum, 검증 규칙을 재생성
python platform/gcp/opencost/generate_pricing.py

# 3. 생성 파일이 최신인지 검증
python platform/gcp/opencost/generate_pricing.py --check

# 4. On-prem Profile 추천 Rule 생성 및 검증
python platform/gcp/opencost/generate_onprem_rightsizing.py
python platform/gcp/opencost/generate_onprem_rightsizing.py --check
```

카탈로그와 생성 파일은 한 커밋으로 관리한다. `--check`는 수동 생성 파일 수정,
생성 누락, 동일 region/type 중복, 출처가 없는 가격을 차단한다.

생성 CSV의 SHA256은 OpenCost Pod template annotation에 기록된다. 가격표가
바뀌면 Argo CD 적용 시 Pod가 자동 재시작되어 이전 CSV를 계속 사용하는 상황을
방지한다.

## 무결성 모니터링

다음 항목은 PrometheusRule과 Kubernetes FinOps 대시보드에서 확인한다.

- 전체 Ready Node 대비 가격 카탈로그 적용 Node 수
- 카탈로그에 없는 Node
- OpenCost 출력 가격과 카탈로그 가격의 불일치
- 필수 노드 라벨과 OpenCost instance type 메타데이터 누락
- AWS/GCP 노드의 provider ID 누락(On-premises는 검사 제외)
- 90일 이상 검토하지 않은 가격 카탈로그

문제가 일정 시간 지속되면 기존 Alertmanager의 `category=finops` 경로를 통해
Slack으로 전달한다. 새 노드가 추가되어도 기존 유형이면 자동 반영되고, 새 유형만
운영자가 가격을 검토하도록 한다.

## 비용 용어

- `Node Cost`: 현재 노드 용량을 유지하는 시간당 플랫폼 기준 비용
- `Allocated Cost`: OpenCost가 사용량과 Request를 바탕으로 Workload에 배분한 비용
- `Request Cost`: 선언된 CPU/Memory Request의 가격 환산값
- `Actual Cost`: 실제 CPU/Memory 사용량의 가격 환산값이며 청구액이 아님
- `Idle Cost`: Node Cost 중 Workload에 할당되지 않은 컴퓨팅 비용
- `Right-sizing Opportunity`: `max(Request Cost - Actual Cost, 0)`인 참고 신호

## 완료 기준

- OpenCost와 ServiceMonitor가 Running/UP 상태다.
- 모든 Node에 `node_total_hourly_cost`가 하나씩 존재한다.
- 모든 Node가 플랫폼·instance type 기준으로 카탈로그와 일치한다.
- 같은 instance type의 Node 증설 시 가격이 자동 적용된다.
- 새 instance type, 가격 불일치, 메트릭 누락이 Grafana와 Slack에서 탐지된다.
- Namespace, Workload, Pod, Container 단위 할당 비용을 조회할 수 있다.
- 대시보드에 실제 청구액이 아닌 플랫폼별 추정 기준임을 명시한다.
