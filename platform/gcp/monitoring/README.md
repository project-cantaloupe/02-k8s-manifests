# GCP monitoring foundation

`monitoring` Namespace와 Tailnet 전용 OpenCost UI NodePort를 관리한다.
Grafana NodePort는 kube-prometheus-stack values에서 관리한다.

MagicDNS가 활성화된 Tailnet 사용자만 다음 주소로 접근한다.

- Grafana: `http://cntlp-gcp-wk-01:30300`
- OpenCost: `http://cntlp-gcp-wk-01:30990`

FQDN은 `cntlp-gcp-wk-01.tail270b85.ts.net`이다. Tailscale IP를 Kubernetes
매니페스트에 고정하지 않고 Node의 MagicDNS 이름과 고정 NodePort를 사용한다.
두 Service는 `externalTrafficPolicy: Local`이고 UI Pod도
`platform=gcp,role=monitoring`으로 고정하므로 worker1을 통해서만 응답한다.
