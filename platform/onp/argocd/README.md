# Argo CD On-Prem 구성

Argo CD 구성요소는 `platform=onp`, `role=devops` 노드에 배치한다. 사용자는
Tailscale MagicDNS HTTPS 주소로 접속한다.

```text
https://cntlp-onp-wk-01.tail270b85.ts.net/
```

접속 흐름은 다음과 같다.

```text
MagicDNS HTTPS:443
  -> Tailscale Serve
  -> http://127.0.0.1:31430/argocd
  -> argocd-server
```

NodePort `31430`은 Tailscale Serve의 로컬 backend다. 팀원이 직접 사용하는
외부 주소로 관리하지 않는다.

`server.insecure: "true"`이므로 backend는 평문 HTTP다. 경로에 `/argocd`가 붙는
것은 `server.basehref`와 `server.rootpath` 설정 때문이다.

Tailscale Serve 설정은 Git이 아니라 노드에서 직접 적용한다. Argo CD가 관리하지
않으므로 매니페스트 병합 후 별도로 실행해야 한다.

```bash
tailscale serve --bg --set-path / http://127.0.0.1:31430/argocd
tailscale serve status
```

이 NodePort 경로가 동작하는 것을 확인한 뒤에만 Istio Ingress 경유 경로를
제거한다. 순서를 바꾸면 Argo CD UI와 그것을 복구할 수단을 동시에 잃는다.

## Tailscale 접근 조건

MagicDNS와 HTTPS Certificates를 tailnet에서 활성화한다. 접근 정책은 IP가
아니라 태그를 기준으로 관리한다.

```text
Source:      group:cntlp-team
Destination: tag:cntlp-ui
Protocol:    TCP
Port:        443
```

On-Prem 노드는 `tag:cntlp-wk,tag:cntlp-ui`로 가입한다. Tailscale auth key는
저장소에 저장하지 않는다.

## 클러스터 재구축

Argo CD는 On-Prem root Kustomization에서 제외되어 있으므로 클러스터를 만든 뒤
한 번 bootstrap한다.

```bash
kubectl diff -k platform/onp/argocd
kubectl apply -k platform/onp/argocd
```

이후 `01-infra-provisioning/ansible`에서 Serve 구성을 적용한다.

```bash
ansible-playbook -i inventories/onp/proxmox.yaml \
  playbooks/site-argocd-access.yaml
```

Tailscale Serve는 `--bg` 설정을 저장하므로 재부팅 뒤에도 복구된다. VM 자체를
재생성한 경우 Ansible 플레이북을 다시 실행한다.

## 검증

```bash
kubectl -n devops rollout status deployment/argocd-server
kubectl -n devops get service argocd-server

curl -I --connect-timeout 5 \
  https://cntlp-onp-wk-01.tail270b85.ts.net/
```

Service에서 `443:31430/TCP`이 확인되고 MagicDNS 주소가 응답하면 정상이다.
