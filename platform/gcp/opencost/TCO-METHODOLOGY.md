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
