# Cantaloupe Observed Right-sizing Advisor

## 목적과 책임 분리

- **Prometheus**: 사용량을 관측하고 모든 후보·안전 신호를 Recording Rule로 계산한다.
- **OpenCost**: Node 단가를 CPU/Memory Request에 배분하고 후보 변경의 비용 영향을 환산한다.
- **Grafana**: 계산 결과와 근거를 표시한다. 정책 계산식을 패널마다 복제하지 않는다.
- **운영자**: 후보를 검토하고 Git의 Request를 변경한 뒤 안정성과 비용을 재검증한다.

자체 Advisor는 Pod를 변경하거나 재시작하지 않으며 결과를 `권장값`이 아닌
**관측 기반 검토 후보**로 표기한다. 별도로 VPA Recommender와 Metrics Server를
설치해 Kubernetes 표준 추천값을 교차 검증하지만, VPA Updater와 Admission
Controller는 설치하지 않는다. 모든 VPA는 `updateMode: Off`이고 추천 결과는
운영자가 검토한 뒤 Git의 request를 직접 바꿀 때만 반영된다.

## 데이터 범위와 신뢰도

현재 Prometheus는 시계열을 15일간 보존하고 20Gi PVC를 사용한다. Right-sizing
Recording Rule은 보존된 시계열 중 최근 7일의 5분 샘플을 사용한다. 따라서 15일
보존은 장애·비용 추세의 전후 비교 여유를 제공하지만, 현재 추천값 자체는 7일
분석 창을 기준으로 한다.

| 코드 | 관측시간 | 표시 | 사용 범위 |
| ---: | ---: | --- | --- |
| 0 | 1시간 미만 | 수집 중 | 후보 판단 금지 |
| 1 | 1~24시간 | 초기 후보 | 시연·기능 검증 |
| 2 | 24~120시간 | 검토 후보 | 담당자 검토 |
| 3 | 120시간 이상 | 현재 운영 기준 | 변경 실험 검토 |

GKE의 장기 분석 사례처럼 14일 기준을 사용하려면 보존기간을 다시 늘리는 것이
아니라 Recording Rule의 분석 창, 관측 신뢰도 구간, OOM·throttling 안전 신호를
함께 14일 정책으로 변경하고 Prometheus 부하와 PVC 여유를 재검증해야 한다.
현재의 7일 결과를 14일 운영 기준과 동일하다고 주장하지 않는다.

## CPU Request 후보

일반 Workload의 컨테이너 템플릿별 후보는 다음과 같다.

```text
CPU 후보 = ceil_10m(CPU Actual P95 / 0.70)
```

- P95는 일상 Peak를 대부분 포함한다.
- 목표 사용률 70%는 약 30%의 Burst 여유를 둔다.
- 최소 10m, 10m 단위로 올림한다.
- CPU Limit은 비용 계산에 포함하지 않으며 자동 추천하지 않는다.
- CPU throttling ratio가 10% 이상이면 축소 비용 기회를 출력하지 않는다.

## Memory Request 후보

Memory는 비압축 자원이므로 P95가 아니라 관측 최대 Working Set을 사용한다.

```text
Memory 후보 = ceil_16Mi(Max Working Set / 0.80)
```

- 목표 사용률 80%로 관측 최대값 위에 25% 용량 여유를 둔다.
- 최소 16Mi, 16Mi 단위로 올림한다.
- 최근 7일 OOMKilled가 있으면 축소 비용 기회를 출력하지 않는다.
- JVM Heap, Cache, 배치 Peak 등 제품 고유 정책은 이 후보보다 우선한다.

P95와 P99도 함께 노출해 Max가 일회성 Spike인지 운영자가 판단할 수 있게 한다.

## Memory Limit 안전성

Memory Limit은 스케줄러 예약량이나 OpenCost 비용이 아니라 OOMKill 경계다. 따라서 높은 Limit을 비용 낭비로 분류하지 않는다.

상태 우선순위는 다음과 같다.

1. 최근 7일 OOMKilled
2. Memory Limit 미설정
3. Actual P99가 현재 Limit의 80% 이상
4. 관측상 압력 없음

중요·Stateful Workload는 제품 정책에 따라 `Request=Limit`을 검토할 수 있지만 Advisor가 자동으로 결정하지 않는다.

## 자동 축소 비용 기회 차단 조건

후보값 자체는 비교를 위해 표시하되 다음 조건에서는 월 배분 개선액을 출력하지 않는다.

- 관측시간 24시간 미만
- 최근 7일 OOMKilled
- CPU throttling ratio 10% 이상
- HPA가 해당 Workload를 대상으로 사용 중
- 원본 Request 또는 사용량 메트릭 누락
- DaemonSet 및 static Pod

StatefulSet과 플랫폼 구성요소는 값이 보여도 제품별 운영 지침과 담당자 승인을 우선한다. 후보는 자동 적용되지 않는다.

## 비용 기회의 의미

```text
후보 Request 비용 = 현재 Request 비용 × 후보 Request / 현재 Request
월 배분 개선액 = 730 × max(현재 Request 비용 - 후보 Request 비용, 0)
```

CPU와 Memory는 독립적으로 계산한다. 한쪽의 과다 Request가 다른 쪽의 부족을 상쇄하지 않는다.

월 배분 개선액은 Kubernetes 내부에서 회수할 수 있는 예약 용량의 비용 가치다. 고정 VM에서는 총 Node 비용이 즉시 감소하지 않는다.

```text
Request 조정
→ Workload 배분비용 감소
→ Node Idle 증가
→ Node 축소·종료 또는 Karpenter consolidation
→ 실제 청구비 감소
```

## 변경 검증 절차

1. 후보, 관측시간, OOM, throttling, HPA 여부를 확인한다.
2. 최근 배포·배치·계절성 트래픽과 제품 고유 지표를 확인한다.
3. Git에서 한 Workload의 Request만 작은 단계로 변경한다.
4. 동일 부하 또는 대표 업무 구간을 재현한다.
5. Pending, latency, 처리시간, 실패율, OOM, throttling을 비교한다.
6. 안정성이 유지되고 Node가 실제 축소됐을 때만 청구 절감으로 기록한다.

## 근거

- AWS Compute Optimizer: P90, P95, P99.5 기반 CPU utilization threshold 제공
- GKE Workload Right-sizing at scale: CPU 목표 사용률과 Memory 최대 사용량/80% 방식 제시
- AWS EKS Best Practices: Request를 실제 사용량에 맞추고 CPU Limit은 throttling 위험을 고려
- OpenCost: Node 비용, Request/Usage 배분, Idle 및 PV 비용 모델
