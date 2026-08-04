# GCP monitoring foundation

`monitoring` Namespace와 Tailnet 전용 OpenCost UI NodePort를 관리한다.
Grafana NodePort는 kube-prometheus-stack values에서 관리한다.

MagicDNS가 활성화된 Tailnet 사용자만 다음 HTTPS 주소로 접근한다.

- Grafana: `https://cntlp-gcp-wk-01.tail270b85.ts.net/grafana/`
- OpenCost: `https://cntlp-gcp-wk-01.tail270b85.ts.net/`

FQDN은 `cntlp-gcp-wk-01.tail270b85.ts.net`이다. Tailscale IP를 Kubernetes
매니페스트에 고정하지 않는다. 사용자의 HTTPS:443 요청은 worker1의 Tailscale
Serve가 받고, OpenCost는 로컬 NodePort `30990`, Grafana `/grafana` 경로는 로컬
NodePort `30300`으로 프록시한다. NodePort는 Tailscale Serve의 backend이며
사용자가 직접 접속하는 주소가 아니다.

두 Service는 `externalTrafficPolicy: Local`이고 UI Pod도
`platform=gcp,role=monitoring`으로 고정하므로 worker1의 로컬 backend가
정상적으로 응답한다.

MagicDNS는 이름 해석만 제공한다. Tailnet 정책에서도 UI를 사용할 사용자 또는
기기에서 `cntlp-gcp-wk-01`의 TCP `443` 포트로 접근할 수 있도록 허용되어
있어야 한다. NodePort를 tailnet 정책에 직접 공개할 필요는 없다.
