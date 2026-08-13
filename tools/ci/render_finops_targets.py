#!/usr/bin/env python3
"""Render GitOps sources covered by the FinOps resource policy."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANAGED_NAMESPACES = {
    "apps",
    "devops",
    "monitoring",
    "logging",
    "secops",
    "audio-ingress",
    "harbor-system",
}
APPLICATION_PATHS = [
    ROOT / "applications",
    ROOT / "platform/gcp/logging-stack",
    ROOT / "platform/aws/secops",
]
REPOSITORY_URL = "https://github.com/project-cantaloupe/02-k8s-manifests.git"


def run(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)
    return completed.stdout


def load_applications() -> list[dict]:
    paths: list[Path] = []
    for entry in APPLICATION_PATHS:
        paths.extend(sorted(entry.rglob("*.yaml")) if entry.is_dir() else [entry])
    applications = []
    for path in paths:
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(document, dict) and document.get("kind") == "Application":
                applications.append(document)
    return applications


def local_value_file(value_file: str) -> Path | None:
    if value_file.startswith("$values/"):
        return ROOT / value_file.removeprefix("$values/")
    return None


def helm_render(application: dict, source: dict, temp: Path) -> str:
    namespace = application["spec"]["destination"]["namespace"]
    release = source.get("helm", {}).get("releaseName", application["metadata"]["name"])
    helm = source.get("helm", {})
    command: list[str]

    if source.get("chart"):
        alias = "repo-" + hashlib.sha256(source["repoURL"].encode()).hexdigest()[:10]
        run(["helm", "repo", "add", alias, source["repoURL"], "--force-update"])
        command = [
            "helm", "template", release, f"{alias}/{source['chart']}",
            "--version", str(source["targetRevision"]), "--namespace", namespace,
        ]
    else:
        clone = temp / ("repo-" + hashlib.sha256(source["repoURL"].encode()).hexdigest()[:10])
        if not clone.exists():
            run(["git", "clone", "--depth", "1", "--branch", str(source["targetRevision"]), source["repoURL"], str(clone)])
        command = ["helm", "template", release, str(clone / source["path"]), "--namespace", namespace]

    values_object = helm.get("valuesObject")
    if values_object:
        values_path = temp / f"{application['metadata']['name']}-values.yaml"
        values_path.write_text(yaml.safe_dump(values_object, sort_keys=False), encoding="utf-8")
        command.extend(["--values", str(values_path)])
    if helm.get("values"):
        values_path = temp / f"{application['metadata']['name']}-inline-values.yaml"
        values_path.write_text(helm["values"], encoding="utf-8")
        command.extend(["--values", str(values_path)])
    for value_file in helm.get("valueFiles", []):
        path = local_value_file(value_file)
        if path:
            if not path.is_file():
                raise FileNotFoundError(f"missing Helm value file: {path}")
            command.extend(["--values", str(path)])
    for parameter in helm.get("parameters", []):
        flag = "--set-string" if parameter.get("forceString") else "--set"
        command.extend([flag, f"{parameter['name']}={parameter['value']}"])
    return run(command)


def local_render(source: dict, namespace: str) -> str:
    path = ROOT / source["path"]
    if not path.exists():
        raise FileNotFoundError(f"missing Git source path: {path}")
    if (path / "kustomization.yaml").exists() or (path / "kustomization.yml").exists():
        return run(["kustomize", "build", str(path)])
    manifests = []
    for candidate in sorted(path.rglob("*.yaml")):
        manifests.append(candidate.read_text(encoding="utf-8"))
    if not manifests:
        raise RuntimeError(f"no renderable manifests in {path}")
    return "\n---\n".join(manifests)


def remove_empty_init_containers(manifest: str) -> str:
    """Drop a Helm-emitted null initContainers field which the API server omits."""
    return re.sub(
        r"(?m)^(?P<indent>[ ]*)initContainers:[ ]*\n(?=(?P=indent)containers:)",
        "",
        manifest,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rendered: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    with tempfile.TemporaryDirectory(prefix="finops-render-") as directory:
        temp = Path(directory)
        for application in load_applications():
            namespace = application.get("spec", {}).get("destination", {}).get("namespace")
            if namespace not in MANAGED_NAMESPACES:
                continue
            sources = application["spec"].get("sources") or [application["spec"].get("source", {})]
            for source in sources:
                if not source or source.get("ref"):
                    continue
                identity = (application["metadata"]["name"], source.get("repoURL", ""), source.get("path", source.get("chart", "")))
                if identity in seen:
                    continue
                seen.add(identity)
                if source.get("chart") or (source.get("path") and source.get("repoURL") != REPOSITORY_URL):
                    rendered.append(helm_render(application, source, temp))
                elif source.get("path") and source.get("repoURL") == REPOSITORY_URL:
                    rendered.append(local_render(source, namespace))

    if not rendered:
        raise RuntimeError("no FinOps policy targets were rendered")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    normalized = [remove_empty_init_containers(source) for source in rendered]
    args.output.write_text("\n---\n".join(normalized), encoding="utf-8")
    print(f"rendered {len(rendered)} GitOps sources to {args.output}")


if __name__ == "__main__":
    main()
