# Workload Right-sizing Methodology

## 책임 분리

- **Prometheus Recording Rules**: 관측값과 검토 후보를 한 곳에서 계산한다.
- **OpenCost**: 노드 단가를 Kubernetes Request에 배분하고 후보 적용 시의 비용 기회를 환산한다.
- **Grafana**: 이미 계산된 값을 조회·비교한다. 패널 내부에 정책 계산식을 복제하지 않는다.
- **운영자**: 후보를 검토하고 YAML을 변경한 뒤 성능, 오류율, OOM, Pending 상태를 재검증한다.

OpenCost는 비용 배분 도구이며 CPU/Memory Request 권장 엔진이 아니다. 따라서 OpenCost의 비용 결과를 사용하되 후보 Request 자체는 별도 정책으로 산출한다.

## Request 검토 후보

현재 구현은 Kubernetes VPA 1.7.1 Recommender 기본값에 맞춘 **근사 검토 후보**다.

| 항목 | 기준 |
| --- | --- |
| 관측 창 | 최근 7일, 5분 샘플 |
| CPU 후보 | P90 × 1.15, 최소 25m, 1m 단위 올림 |
| Memory 후보 | P90 × 1.15, 최소 250MiB, 1MiB 단위 올림 |
| 화면 비교값 | Actual P95 |
| 검토 시작 조건 | 24시간 이상 관측, 최근 7일 OOM 신호 없음 |
| 자동 적용 | 사용하지 않음 |

P90은 후보 산정 기준이고 P95는 운영자가 여유를 확인하기 위한 비교값이다. 이 구현은 VPA의 decaying histogram, confidence bounds 및 memory OOM estimator 전체를 재현하지 않으므로 `권장값`이 아니라 `검토 후보`로 표기한다. 운영 자동화가 필요해지면 VPA Recommender를 `updateMode: Off`로 도입하고 `target/lowerBound/upperBound`를 원본 권고로 사용한다.

## Memory Limit

Memory Limit은 스케줄러의 예약량이나 OpenCost Request 비용이 아니라 OOMKill 경계다. 따라서 높은 Limit을 비용 낭비로 분류하거나 임의의 권장 Limit으로 낮추지 않는다.

상태 우선순위는 다음과 같다.

1. 최근 7일 OOM 신호
2. Memory Limit 미설정
3. 현재 Limit이 관측 Actual P99 이하
4. 관측 위반 없음

`관측 위반 없음`은 미래 안전 보장이 아니다. 트래픽 피크, 메모리 누수, JVM/런타임 특성 및 팀 정책을 함께 검토해야 한다.

## 비용 기회의 의미

후보 비용은 현재 OpenCost Request 배분비용에 `후보 Request / 현재 Request` 비율을 적용한다. 월 비용은 시간당 값을 730시간으로 환산한다.

이 값은 **Kubernetes 내부 배분비용 회수 가능성**이다. 고정 크기 VM에서는 Request를 줄여도 클라우드 청구액이 즉시 줄지 않는다. 실제 청구 절감은 이후 노드 축소, VM 사양 변경 또는 Karpenter consolidation으로 유휴 용량이 제거될 때 실현된다.

## 변경 승인 절차

1. 7일 관측을 우선 사용하고, 24시간 후보는 시연·초기 검토로만 취급한다.
2. 최근 배포, 배치 작업, 계절성 트래픽과 OOM 이력을 확인한다.
3. Deployment/StatefulSet의 컨테이너 Request를 작은 단계로 변경한다.
4. 재배포 후 Pending, throttling, P95 latency, 오류율, OOM을 관찰한다.
5. 안정성이 유지되고 노드 용량이 실제로 축소됐을 때만 청구 절감으로 보고한다.

## 기준 출처

- Kubernetes Autoscaler VPA 1.7.1 recommender defaults: `pkg/recommender/config/config.go`
- OpenCost allocation metrics and node pricing
