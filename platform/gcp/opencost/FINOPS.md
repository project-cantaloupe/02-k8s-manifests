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
