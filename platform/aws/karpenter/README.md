# AWS Karpenter

Self-managed `cntlp-k8s` 클러스터에서 Audio Burst 전용 AWS Service Worker의
생성·가입·축소 lifecycle을 검증하는 Karpenter 구성이다.

## 범위

- Karpenter `1.14.0` Controller와 CRD 설치
- AWS Control Plane Node에 Controller 1 replica 고정
- 기존 Private Subnet, Security Group, Worker Instance Profile 재사용
- Custom Golden AMI와 Tailscale·kubeadm bootstrap 실행기 사용
- `t3.small` On-Demand Node 최대 두 대 제한

동시 가입 시 Kubernetes와 Tailscale 이름이 충돌하지 않도록 Node 이름을
`cntlp-aws-wk-98`, `cntlp-aws-wk-99`로 예약한다. 각 NodePool과 EC2NodeClass는
예약 이름 하나와 최대 Node 한 대만 소유한다. 두 NodePool은 공통
`cantaloupe.io/node-purpose=audio-burst` 라벨을 제공하므로 Burst Pod는 특정
예약 번호를 알 필요가 없다.

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
Pod가 `cantaloupe.io/node-purpose=audio-burst`를 요구하므로 기존 고정 Worker에는
배치되지 않고 두 Audio Burst NodePool 중 가용한 풀의 Node 생성을 유발한다.

## FinOps 비교 경계

KEDA는 `audio-transcode-burst`를 0~6개로 조정한다. 두 NodePool은 평상시 Node를
유지하지 않고 Pending Burst Pod가 있을 때만 각각 최대 한 대를 만든다.

- Baseline `250m/256Mi`: Burst 6개와 DaemonSet Request가 한 `t3.small`에
  들어가지 않아 Node 두 대가 필요할 것으로 예상한다.
- Candidate `50m/224Mi`: 동일 Burst 6개가 Node 한 대에 들어갈 것으로 예상한다.

이 값은 Scheduler Request 계산에 따른 가설이다. 실제 Node 수, Node-minute,
READY Track, 처리 P95, OOM·Restart·MemoryPressure를 같은 부하에서 확인한 뒤에만
비용 절감으로 판정한다.
