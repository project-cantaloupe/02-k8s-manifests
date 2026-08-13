# governance

전 클러스터에 공통으로 거는 보안·비용 규칙.

**집행 주체가 둘이다.** 파드 하드닝 기본선은 Kubernetes 내장 기능인
**Pod Security Admission(PSA)** 이 맡고, 그 밖의 전부를 **Kyverno** 가 맡는다.

## 규칙이 적용되는 네 경로

| 경로 | 하는 일 | 집행 |
|---|---|---|
| `namespaces/` | 네임스페이스별 **파드 하드닝 등급** | PSA (API 서버 내장) |
| `secops/`, `finops/` | 공통 검증·관측 정책 (ClusterPolicy) | Kyverno |
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
| `namespaces/` | 16개 네임스페이스 | PSA 등급 (파드 하드닝) | enforce |
| `secops/generate-default-network-policies` | 새 네임스페이스 | default-deny + 같은 ns 허용 생성 | generate |
| `secops/require-image-registry` | `apps` | ECR 에서만 당긴다 | **Audit** |
| `secops/disallow-latest-tag` | 운영 비용 대상 ns 7개 | 태그 필수, `latest` 금지 | **Audit** |
| `secops/disallow-default-namespace` | `default` | 파드 생성 금지 | **Audit** |
| `finops/require-resource-limits` | 운영 비용 대상 ns 7개 | CPU·Mem requests, Mem limit | **Audit** |

### Audit 정책을 읽는 법

PolicyReport 건수는 ReplicaSet·Job의 생성과 정리에 따라 계속 변하므로 문서에
고정하지 않는다. 현재 값은 `kubectl get polr -A`로 확인한다.

| 정책 | 현재 의미 | 다음 판단 |
|---|---|---|
| `require-resource-limits` | 실제 사용량과 선언값 차이를 찾는 관측 신호 | Grafana와 함께 검토하며 Audit 유지 |
| `require-image-registry` | 기존 ECR-only 결정과 현재 Harbor SHA 배포의 차이를 기록 | 런타임 Registry 결정을 다시 확정하기 전 Enforce 금지 |
| `disallow-latest-tag` | 태그 누락·`latest` 사용을 기록 | 배포 경로별 고정 태그 지원 여부 확인 |
| `disallow-default-namespace` | `default` 업무 Pod 생성을 기록 | 기본 Namespace의 시스템 객체와 구분해 판단 |

현재 오디오 CI는 Harbor에 커밋 SHA 이미지를 Push하고 `03-app-audio`가
`02-k8s-manifests`의 이미지 태그를 갱신한다. 따라서 ECR만 허용하는
`require-image-registry`는 현재 배포 현실과 일치하지 않으며, Audit 결과는
예상된 설계 차이다. 이를 리소스 제한 위반과 한 묶음으로 보고 강제 전환하지 않는다.

대상 범위는 규약 7절을 따른다 — 실제 비용이 발생하고 배포 설정을 소유하는
서비스 네임스페이스 일곱. 클러스터 핵심 시스템 네임스페이스와 `kyverno`는 제외한다
(`00-cantaloupe-resources/k8s-labeling-convention.md`).

## 정책 집행 모드는 목적에 맞춘다

`validationFailureAction: Audit`은 위반을 기록만 하고 통과시킨다. 이미지 출처와
배포 금지처럼 반드시 막아야 하는 규칙은 검증 후 Enforce로 전환한다. 반면
`require-resource-limits`는 Grafana의 실제 사용량과 함께 보는 FinOps 관측
신호이므로 Audit를 유지하고 숫자를 억지로 채우기 위한 변경은 하지 않는다.

**이유가 있는 경우가 하나 있다 — 아직 안 세운 서드파티 스택.**
Harbor·ArgoCD·Prometheus 같은 차트는 위반 목록을 미리 알 수 없다.
모르는 채로 Enforce 를 켜면 클러스터가 자기 배포를 막는다
(→ `tasks/todo/002_bootstrap-blockers.md` 2번). 그럴 때만 이 순서를 쓴다.

```
Audit 배포 → PolicyReport 확인 → exceptions/ 작성 → Enforce 전환
```

PSA 쪽은 `enforce`를 안전한 등급에 두고 `warn`/`audit`을 한 단계 높게 둬서
격차가 계속 보이게 한다. Kyverno 정책은 차단 목적과 관측 목적을 문서에
명시해 Audit가 단순 미완료 상태로 오해되지 않게 한다.

`background: true` 인 정책은 이미 존재하는 자원도 주기적으로 스캔한다.
결과는 `kubectl get polr -A` 와 `kubectl get cpolr` 로 본다.

현재 FinOps 정책은 운영 비용 대상 7개 Namespace의 container와 initContainer에
CPU·Memory requests와 Memory limit이 있는지 검사한다. CPU limit은 전역
강제하지 않는다.

일반 워크로드의 `app`, `area`, `platform`과 다중 플랫폼 DaemonSet의
`app`, `area` 라벨 검사는 팀 워크로드가 작성된 뒤 별도 정책으로 추가한다.

## 예외를 추가할 때

`exceptions/`에 파일을 만들고 **사유·승인자·재검토 시점**을 적는다.
만료 없는 예외는 영구 면제가 된다.
