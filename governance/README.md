# governance

전 클러스터에 공통으로 거는 보안·비용 규칙.

**집행 주체가 둘이다.** 파드 하드닝 기본선은 Kubernetes 내장 기능인
**Pod Security Admission(PSA)** 이 맡고, 그 밖의 전부를 **Kyverno** 가 맡는다.

## 규칙이 적용되는 네 경로

| 경로 | 하는 일 | 집행 |
|---|---|---|
| `namespaces/` | 네임스페이스별 **파드 하드닝 등급** | PSA (API 서버 내장) |
| `secops/`, `finops/` | 전체에 **강제** (ClusterPolicy) | Kyverno |
| `exceptions/` | 특정 대상만 **면제** (PolicyException) | Kyverno |
| `platform/*/policies/`, `apps/*/policies/` | 특정 대상에만 **추가** | Kyverno |

빼기(`exceptions/`)와 더하기(`*/policies/`)를 다른 곳에 둔다.
`ls exceptions/` 하나로 "기준에서 벗어난 게 뭐냐"에 답할 수 있어야 한다.
`ls namespaces/` 하나로 "각 네임스페이스가 몇 등급이냐"에 답할 수 있어야 한다.

## 왜 둘로 나누나

특권 컨테이너·호스트 네임스페이스·hostPath·권한 상승·capability 추가·root 실행
여섯 가지는 **Pod Security Standards 의 `restricted` 등급이 정확히 그대로
정의한다.** 같은 것을 Kyverno 로 쓰면 정책 여섯 장을 우리가 쓰고 테스트하고
유지해야 하고, 어드미션 웹훅을 한 번 더 왕복한다.

PSA 는 네임스페이스 라벨 세 줄이고 설치할 것도 유지할 것도 없다.

**Kyverno 는 PSA 가 표현할 수 없는 것을 맡는다** — 이미지 레지스트리 제한,
라벨 규약 강제, 자원 요청·제한, 네임스페이스 생성 시 NetworkPolicy 자동 생성
(`generate`), nodeSelector 주입(`mutate`).

세 등급의 정확한 항목과 앵커 문법은
`references/20260803_secops-admission-and-network-policy.md` 에 있다.

⚠️ **PSA 는 파드 생성 시점에만 본다.** 이미 도는 파드에 소급되지 않는다.
등급을 올릴 때는 그 네임스페이스의 파드를 다시 띄워야 실제로 적용된다.

**같은 규칙을 두 곳에서 걸지 않는다.** `require-run-as-nonroot` 를 지운 것이
그래서다. PSA `restricted` 가 같은 것을 더 강하게 한다 — Kyverno 쪽은 파드
레벨에 `true` 를 적고 컨테이너가 `false` 로 덮어쓰는 경우를 pattern 문법으로
막지 못했다. 두 곳에 두면 고칠 곳이 둘이고 약한 쪽이 진실처럼 보인다.

## 현재 정책 목록

| 정책 | 대상 | 하는 일 | 집행 |
|---|---|---|---|
| `namespaces/` | 14개 네임스페이스 | PSA 등급 (파드 하드닝) | enforce |
| `secops/generate-default-network-policies` | 새 네임스페이스 | default-deny + 같은 ns 허용 생성 | generate |
| `secops/require-image-registry` | `apps` | ECR 에서만 당긴다 | **Audit** |
| `secops/disallow-latest-tag` | 팀 ns 7개 | 태그 필수, `latest` 금지 | **Audit** |
| `secops/disallow-default-namespace` | `default` | 파드 생성 금지 | **Audit** |
| `finops/require-resource-limits` | 팀 ns 7개 | CPU·Mem requests, Mem limit | **Audit** |

### Audit 로 남아 있는 것 — 미완료 목록

**2026-08-06 착지 시점 실측.** 네 정책 전부 Audit 이고, 아래가 각각의
Enforce 전환 조건이다. 이 표가 비면 완료다.

| 정책 | 위반 | Enforce 전환 조건 |
|---|---|---|
| `require-resource-limits` | 9건 — Argo CD·Harbor·OpenSearch | 차트 values 로 limits 를 채우거나 `exceptions/` |
| `require-image-registry` | 4건 — `apps` 파드 **전부** | **결정이 필요하다** — 아래 |
| `disallow-latest-tag` | 3건 — Harbor·OpenSearch 보조 컨테이너 | 차트 values 로 태그 고정 |
| `disallow-default-namespace` | **0건** | 나머지 셋과 같이 올린다 |

`require-image-registry` 만 성격이 다르다. 나머지 셋은 위 규칙이 허용하는
**"아직 안 세운 서드파티 스택"** 이지만, **이건 우리 앱이 걸린 것이다.**
지금 오디오 이미지는 GHCR 에 있고 `ghcr-pull` Secret 으로 당긴다
(`apps/audio/README.md`). ECR 로 옮길지, GHCR 을 허용 목록에 넣을지가
정해져야 Enforce 로 갈 수 있다. **정책과 현실 중 어느 쪽이 틀렸는지의
문제라서 예외로 덮을 일이 아니다.**

이 정책이 Enforce 로 쓰였던 것은 작성 당시 `apps` 가 비어 있어 대조할
워크로드가 없었기 때문이다. 워크로드가 생기자 4건이 나왔다.

대상 범위는 규약 7절을 따른다 — 팀 네임스페이스 일곱. 시스템 네임스페이스와
`kyverno` 는 제외한다
(`00-cantaloupe-resources/k8s-labeling-convention.md`).

## 정책은 Enforce로 쓴다

`validationFailureAction: Audit`은 위반을 기록만 하고 통과시킨다.
그건 규칙이 아니라 통계다. 새 정책을 넣을 때 이유 없이 Audit 로 두지 않는다.

**이유가 있는 경우가 하나 있다 — 아직 안 세운 서드파티 스택.**
Harbor·ArgoCD·Prometheus 같은 차트는 위반 목록을 미리 알 수 없다.
모르는 채로 Enforce 를 켜면 클러스터가 자기 배포를 막는다
(→ `tasks/todo/002_bootstrap-blockers.md` 2번). 그럴 때만 이 순서를 쓴다.

```
Audit 배포 → PolicyReport 확인 → exceptions/ 작성 → Enforce 전환
```

**Enforce 전환이 그 정책의 완료 조건이다.** Audit 로 남아 있는 정책은
미완료로 본다. PSA 쪽도 같은 구조다 — `enforce` 는 안전한 등급에 두고
`warn`/`audit` 을 한 단계 높게 둬서 격차가 계속 보이게 한다.

`background: true` 인 정책은 이미 존재하는 자원도 주기적으로 스캔한다.
결과는 `kubectl get polr -A` 와 `kubectl get cpolr` 로 본다.

현재 FinOps 정책은 팀 Namespace의 container와 initContainer에
CPU·Memory requests와 Memory limit이 있는지 검사한다. CPU limit은 전역
강제하지 않는다.

일반 워크로드의 `app`, `area`, `platform`과 다중 플랫폼 DaemonSet의
`app`, `area` 라벨 검사는 팀 워크로드가 작성된 뒤 별도 정책으로 추가한다.

## 예외를 추가할 때

`exceptions/`에 파일을 만들고 **사유·승인자·재검토 시점**을 적는다.
만료 없는 예외는 영구 면제가 된다.
