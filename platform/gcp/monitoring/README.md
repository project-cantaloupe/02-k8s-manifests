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

MagicDNS는 이름 해석만 제공한다. Tailnet 정책에서도 UI를 사용할 사용자 또는
기기에서 `cntlp-gcp-wk-01`의 TCP `30300`, `30990` 포트로 접근할 수 있도록
허용되어 있어야 한다. 이름이 `100.110.166.60`으로 정상 해석되더라도 정책이
허용하지 않으면 브라우저 연결은 시간 초과된다.
