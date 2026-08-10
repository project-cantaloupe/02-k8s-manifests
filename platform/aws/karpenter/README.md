# AWS Karpenter

Self-managed `cntlp-k8s` 클러스터에서 AWS Service Worker 한 대의 생성·가입·축소
lifecycle을 검증하는 Karpenter 구성이다.

## 범위

- Karpenter `1.14.0` Controller와 CRD 설치
- AWS Control Plane Node에 Controller 1 replica 고정
- 기존 Private Subnet, Security Group, Worker Instance Profile 재사용
- Custom Golden AMI와 Tailscale·kubeadm bootstrap 실행기 사용
- `t3.small` On-Demand Node 최대 한 대 제한

현재 Node 이름은 검증 예약명 `cntlp-aws-wk-99`로 고정한다. NodePool의 최대
Node 수도 1로 제한하며 다중 NodePool 전환 전에는 고유한 두 자리 Node 번호
할당 계약이 필요하다.

## 배포 전 조건

1. `01-infra-provisioning/terraform/aws/karpenter`의 Controller Policy,
   Tailscale OAuth Secret, kubeadm Join Secret 기반 적용
2. `--karpenter-node`를 지원하는 Golden AMI 생성과 `ec2nodeclass.yaml`의
   정확한 AMI 이름 갱신
3. `tag:cntlp-wk` 제한 Tailscale OAuth Client Secret 등록
4. Control Plane의 kubeadm token 회전 systemd timer 활성화

Secret 값은 Git, Terraform 변수, Terraform state, EC2 UserData에 저장하지 않는다.
Worker는 Instance Profile로 두 Secret을 각각 읽는다. OAuth Client가 ephemeral
인증 키를 발급하고, kubeadm Join 정보는 TTL 24시간·12시간 회전으로 유지한다.

## 검증 workload

`tests/scale-up.yaml`은 운영 Kustomization에 포함하지 않는다. Controller와
NodePool Ready 확인 후 제한된 E2E에서만 적용하며, 검증 완료 즉시 삭제한다.
Pod가 `karpenter.sh/nodepool=aws-service`를 요구하므로 기존 고정 Worker에는
배치되지 않고 Karpenter Node 생성을 유발한다.
