# Cantaloupe OpenCost 기준

## Phase 1 가격 모델

이 환경의 비용은 실제 AWS/GCP 청구액이 아니라 Kubernetes 자원 효율을
비교하기 위한 공통 벤치마크다.

| 항목 | 단가 |
| --- | ---: |
| CPU | $0.03 / core-hour |
| Memory | $0.004 / GiB-hour |
| Storage | $0.000137 / GiB-hour |
| GPU/Network | $0 |

AWS, GCP, On-premises에 동일한 단가를 적용한다. 노드 가격은 노드의 CPU와
메모리 용량에 따라 자동 계산되므로 노드를 추가해도 이름별 CSV 수정이
필요하지 않다.

Phase 2에서 플랫폼별 가상 단가를 도입하더라도 실제 클라우드 청구액으로
표현하지 않고 비교 실험용 가격 모델임을 대시보드에 표시한다.

## 비용 용어

- `Node Cost`: 현재 노드 용량을 유지하는 시간당 기준 비용
- `Allocated Cost`: OpenCost가 사용량과 Request를 바탕으로 Workload에 할당한 비용
- `Request Cost`: 선언된 CPU/Memory Request의 가격 환산값
- `Actual Cost`: 실제 CPU/Memory 사용량의 가격 환산값이며 청구액이 아님
- `Idle Cost`: Node Cost 중 Workload에 할당되지 않은 컴퓨팅 비용
- `Unmounted Cost`: 실행 중인 Pod에 연결하지 못한 PV/LB 등 자산 비용
- `Right-sizing Opportunity`: `max(Request Cost - Actual Cost, 0)`인 참고 신호

## 완료 기준

- OpenCost와 ServiceMonitor가 Running/UP 상태다.
- 모든 Node에 `node_total_hourly_cost`가 하나씩 존재한다.
- Node 가격 지표에 `node`, `instance_type`, `provider_id`가 존재한다.
- Node를 추가했을 때 별도 가격 CSV 없이 비용이 자동 생성된다.
- Namespace, Workload, Pod, Container 단위 할당 비용을 조회할 수 있다.
- `platform`, `role`, `namespace` 기준으로 비용을 분류할 수 있다.
- Request, Actual, Allocated 비용을 서로 다른 의미로 표시한다.
- 가격 모델과 대시보드 모두 실제 청구액이 아닌 추정치임을 명시한다.
