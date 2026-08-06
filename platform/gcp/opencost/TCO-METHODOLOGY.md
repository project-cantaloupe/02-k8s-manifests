# Cantaloupe On-prem TCO v1

## 적용 범위

이 문서는 `cntlp-onp-wk-01`의 Compute 시간당 기준가격을 정의한다. 실제 청구서가
아니라 플랫폼 비교와 OpenCost 비용 배분을 위한 3년 replacement-cost benchmark다.

## 대상 자원

| 구분 | 사양 |
| --- | --- |
| Proxmox 물리 호스트 | AMD Ryzen 5 5600U, 6 core/12 thread, 24 GiB RAM |
| Kubernetes VM | 8 vCPU, 16 GiB RAM |
| VM 배분율 | CPU 8/12, Memory 16/24 = 66.67% |

## 산정 근거

Microsoft Azure Migrate Business Case의 공개 On-prem TCO 모델을 기준으로 서버
교체원가, 유지보수, 전력/PUE 및 호스트 인프라 관리비를 포함한다.

| 항목 | 기준 | 금액 |
| --- | --- | ---: |
| 서버 교체원가 | `(16.232 × (12/24) + 113.87) × 6 core` | $731.92 |
| 유지보수 | 교체원가의 연 10% | $73.19/year |
| 전력·냉각 | `6 core × 0.009 kWh × load 2.0 × PUE 1.8 × 8,760h × $0.10` | $170.29/year |
| 호스트 관리 | Monitoring $145 + Patch $145 | $290.00/year |

```text
((731.92 + 3×73.19 + 3×170.29 + 3×290.00) × 66.67%) ÷ (3×8,760)
= $0.05917/hour
≈ $0.06/hour
```

## 포함·제외 기준

포함 항목은 Compute/Memory 하드웨어 교체원가, 유지보수, 전력·냉각 및 Proxmox
호스트 관리다. Local disk/PV, 공통 네트워크, Kubernetes 공통 운영 인력,
애플리케이션 인력 및 다운타임은 제외한다. AWS/GCP VM 공개가격과 비교 범위를
맞추기 위해 저장소 비용은 Compute 가격과 분리한다.

실제 장비 구매가, 전력계 측정값 또는 조직의 인건비 기준을 확보하면 이 문서의
가정과 `pricing-catalog.yaml`의 최종 시간당 가격만 함께 갱신한다.

## On-prem Right-sizing Profile

On-prem 추천은 Cloud VM SKU를 흉내 내지 않고 회사가 실제로 제공할 수 있는
가상 하드웨어 Profile 중에서 선택한다. 현재 물리 호스트는 12 vCPU 환산과
24 GiB를 제공하고, 전체 시간당 TCO는 기존 `8 vCPU/16 GiB = $0.06/hour`
산정과 일치하도록 `$0.09/hour`로 역산한다.

Profile 비용은 CPU 예약비율과 Memory 예약비율 중 더 큰 값을 사용한다. 이는
한 자원이 병목이면 남은 호스트 용량을 다른 VM에 완전히 재배치할 수 없다는
보수적 가정이다.

```text
profile hourly TCO
= host hourly TCO
  * max(profile vCPU / host vCPU, profile GiB / host GiB)
```

| Profile | vCPU | Memory | 시간당 TCO |
| --- | ---: | ---: | ---: |
| onp-small | 2 | 4 GiB | $0.015 |
| onp-medium | 4 | 8 GiB | $0.030 |
| onp-memory-balanced | 4 | 12 GiB | $0.045 |
| onp-large | 8 | 16 GiB | $0.060 |

추천 필요 용량은 최근 7일 Node 전체 Container 사용량 P95에 CPU/Memory 30%
여유를 적용하고 OS·kubelet을 위해 0.5 CPU와 1 GiB를 추가한다. 이 필요 용량을
만족하는 가장 저렴한 Profile을 권장한다.

추천과 적용 가능 여부는 별도다. 현재 Pod Request 합계가 권장 Profile의 90%를
넘으면 `Workload Right-sizing 선행`으로 판단한다. 최근 OOMKilled 또는 Node
MemoryPressure가 있으면 사양 축소를 안전하다고 표시하지 않는다. 추천은 자동
적용하지 않으며 Drain, 재스케줄링, 장애 시 여유와 서비스 SLO를 검증한 뒤
승인한다.

관측 신뢰도는 6시간 미만, 6~24시간, 24시간~7일, 7일 이상으로 분리한다.
최소 24시간이 확보되기 전에는 Profile과 예상 절감액을 참고값으로만 표시하며
`검토 가능`으로 판정하지 않는다. 이 기준은 짧은 프로젝트에서도 후보를 숨기지
않으면서 장기 검증이 끝난 것처럼 과장하지 않기 위한 안전장치다.

정책의 실행 가능한 단일 원본은 `onprem-rightsizing-policy.yaml`이며,
`generate_onprem_rightsizing.py`가 Prometheus Recording/Alert Rule을 생성한다.
실제 서버 재고나 회사 TCO가 확보되면 Profile과 Host TCO만 변경하고 같은 추천
및 검증 흐름을 유지한다.
