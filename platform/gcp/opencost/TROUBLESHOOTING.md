# OpenCost mixed-provider pricing troubleshooting

## 증상과 원인

이 클러스터는 AWS, GCP, 온프레미스 Node가 하나의 Kubernetes control plane에
등록되어 있다. OpenCost `1.121.0`의 기본 Provider 자동 감지는 한 Node를 기준으로
프로세스 전체 Provider 하나를 선택한다. 실제 테스트에서는 GCP Provider가 선택되어
AWS 인스턴스 타입을 GCP 가격표에서 찾지 못했고, 비어 있는 가격이 공통 기본 단가로
대체되었다. 따라서 기본 Provider 자동 감지를 혼합 클라우드 가격 모델로 사용하면
안 된다.

해결은 OpenCost를 공급자별로 세 개 설치하는 것이 아니라, 단일 OpenCost에서 CSV
Provider를 강제하고 모든 Node의 정확한 시간당 가격을 한 표에 넣는 것이다.

```yaml
USE_CUSTOM_PROVIDER: "true"
USE_CSV_PROVIDER: "true"
CSV_PATH: /var/configs/node-pricing.csv
```

`values.yaml`의 `opencost-node-pricing` ConfigMap이 가격표를 제공하고 같은 Helm
release가 이를 `/var/configs/node-pricing.csv`에 read-only로 마운트한다.

## 2026-08-05 가격 근거

모든 금액은 USD이며 VAT, 약정, Spot, 크레딧 및 협상 할인을 제외한 공개
On-Demand 가격이다.

| 대상 | 계산 | 시간당 가격 |
|---|---:|---:|
| AWS `m7i-flex.large` 서울 | 공식 Price List의 Linux/Shared/Used | `$0.117710000` |
| AWS `t3.small` 서울 | 공식 Price List의 Linux/Shared/Used | `$0.026000000` |
| GCP `e2-custom-4-8192` 서울 | `4 × 0.02942774 + 8 × 0.003926066` | `$0.149119488` |
| GCP `e2-standard-4` 서울 | `4 × 0.02802642 + 16 × 0.00373911` | `$0.171931440` |
| 온프레미스 `8 vCPU/16 GiB` | `8 × 0.03 + 16 × 0.004` | `$0.304000000` |
| GCP zonal `pd-standard` 서울 | `$0.052/GiB-month ÷ 730` | `$0.000071233/GiB-hour` |

공식 증거 URL:

- AWS 서울 EC2 최신 Price List CSV:
  <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-2/index.csv>
- AWS On-Demand 가격 설명: <https://aws.amazon.com/ec2/pricing/on-demand/>
- GCP E2 Custom Core 서울 (`F10F-0364-8D62`):
  <https://cloud.google.com/skus?currency=USD&filter=F10F-0364-8D62>
- GCP E2 Custom RAM 서울 (`B5E6-7318-DBF9`):
  <https://cloud.google.com/skus?currency=USD&filter=B5E6-7318-DBF9>
- GCP E2 Core 서울 (`9304-94C4-2117`):
  <https://cloud.google.com/skus?currency=USD&filter=9304-94C4-2117>
- GCP E2 RAM 서울 (`D715-4E57-BAFB`):
  <https://cloud.google.com/skus?currency=USD&filter=D715-4E57-BAFB>
- GCP zonal standard PD 서울 (`0306-B164-A7B7`):
  <https://cloud.google.com/skus?currency=USD&filter=0306-B164-A7B7>

AWS CSV publication date는 `2026-08-03T19:42:46Z`, version은
`20260803194246`, 가격 effective date는 `2026-08-01`이었다. GCP SKU 페이지는
조회 시점의 현재 USD 가격을 표시한다. 가격 갱신 시 URL과 조회일, AWS version을
함께 변경한다.

## 검증 명령

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,PROVIDER:.spec.providerID,TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,REGION:.metadata.labels.topology\.kubernetes\.io/region,CPU:.status.capacity.cpu,MEM:.status.capacity.memory'

kubectl -n monitoring get configmap opencost-node-pricing \
  -o jsonpath='{.data.node-pricing\.csv}'

kubectl -n monitoring get deploy opencost \
  -o jsonpath='{range .spec.template.spec.containers[?(@.name=="opencost")].env[*]}{.name}{"="}{.value}{"\n"}{end}'

kubectl -n monitoring logs deploy/opencost -c opencost --since=10m | \
  grep -E 'Using CSV Provider|Found price info|Unable to find provider ID|falling back'

kubectl -n monitoring port-forward svc/opencost 9003:9003
curl -s http://127.0.0.1:9003/metrics | \
  grep -E '^node_(total|cpu|ram)_hourly_cost'

curl -s 'http://127.0.0.1:9003/model/allocation?window=1h&aggregate=node' | jq .
```

정상 기준:

1. ConfigMap 가격표에 현재 Node 다섯 개가 각각 한 번 존재한다.
2. OpenCost 로그에 CSV Provider와 다섯 Node 가격 로딩이 보인다.
3. `node_total_hourly_cost`가 표의 각 Node 가격과 일치한다.
4. 가격 매칭 메타데이터가 다섯 Node 모두 `csvExact`이며 fallback이 없다.
5. Allocation API의 Node별 비용이 동일한 가격 모델을 사용한다.

Node 이름이 변경되거나 Node가 추가되면 가격표 행도 같은 변경에 포함해야 한다.
행이 누락되면 OpenCost가 fallback 가격을 사용할 수 있으므로 배포 검증에서 반드시
현재 Node 집합과 CSV Node 집합을 비교한다.

## 알려진 범위

- 이 모델은 공개 단가 기반 Kubernetes allocation이며 실제 청구서 reconciliation이
  아니다.
- `t3.small`의 Unlimited CPU credit, 네트워크 송신, 공인 IPv4, AWS EBS 등은 별도다.
- 온프레미스 가격은 실제 현금 청구가 아닌 프로젝트 비교용 가상 원가다.
- GCP Cloud Billing API는 현재 프로젝트에서 비활성화되어 있었지만 CSV Provider는
  런타임 Billing API 권한이나 API key를 요구하지 않는다.
