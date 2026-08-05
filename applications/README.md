# Argo CD Applications

이 디렉터리는 Root Application이 관리하는 운영용 Argo CD `Application`
목록이다.

## 동작 원리

```text
cantaloupe-root
  -> applications/kustomization.yaml
       -> applications/<part>.yaml
            -> Application에 지정된 Git 경로의 매니페스트
```

Root Application은 `kustomization.yaml`의 `resources`에 명시된 파일만
생성한다. 현재 Jenkins, Harbor, GCP Storage, Istio Base, Istiod와 Istio Ingress
Gateway가 등록되어 있다. AWS Audio Edge Smoke는 단계별 검증 전까지 Root 목록에
등록하지 않는다.

## 새 파트 배포 방법

1. `platform/<platform>/<part>/` 또는 `apps/<app>/`에 매니페스트를 작성한다.
2. `applications/<part>.yaml`에 Application을 작성한다. 예를 들어
   `platform/gcp/kube-prometheus-stack`을 배포하려면 아래 내용을
   `applications/monitoring.yaml` 파일로 작성한다.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring-stack
  namespace: devops
spec:
  project: default
  source:
    repoURL: https://github.com/project-cantaloupe/02-k8s-manifests.git
    targetRevision: main
    path: platform/gcp/kube-prometheus-stack
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

3. `applications/kustomization.yaml`에 2번에서 작성한 `monitoring.yaml`을
   등록한다.

```yaml
resources:
  - monitoring.yaml
```

4. PR을 `main`에 병합한다.
5. Root Application이 변경을 감지해 Application을 생성하고, 생성된
   Application이 지정된 Git 경로를 배포한다.

운영 Application의 `targetRevision`은 `main`을 사용한다. 기능 브랜치의
Application은 Root 목록에 등록하지 않고 별도의 이름과 Namespace로 검증한다.
비밀 값과 repository credential은 Git에 저장하지 않는다.
