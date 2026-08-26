"""Deployment sequencing and secret-scoping invariants for the kind lab.

These tests read committed manifests and scripts. They do not need a cluster.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
K8S = REPO_ROOT / "infra" / "k8s"
DEPLOY_SH = REPO_ROOT / "scripts" / "k8s" / "deploy.sh"

APP_DEPLOY_FILES = {
    "api-deployment.yaml": {"stockviz-db", "stockviz-auth"},
    "web-deployment.yaml": {"stockviz-db", "stockviz-auth"},
    "scheduler-deployment.yaml": {"stockviz-db"},
    "outbox-publisher-deployment.yaml": {"stockviz-db"},
    "trade-activity-deployment.yaml": {"stockviz-db"},
    "market-ingest-deployment.yaml": {"stockviz-db", "stockviz-market-provider"},
    "market-analytics-deployment.yaml": {"stockviz-db"},
    "news-ingest-deployment.yaml": {"stockviz-db", "stockviz-news-provider"},
    "news-sentiment-deployment.yaml": {"stockviz-db", "stockviz-sentiment-provider"},
    "sentiment-aggregate-deployment.yaml": {"stockviz-db"},
}


def _secret_names(text: str) -> set[str]:
    names: set[str] = set()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "secretKeyRef" not in line:
            continue
        for follow in lines[i + 1 : i + 4]:
            stripped = follow.strip()
            if stripped.startswith("name:"):
                names.add(stripped.split(":", 1)[1].strip())
                break
    return names


def test_deploy_sh_applies_apps_only_after_migration_complete() -> None:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    postgres_ready = text.index('log "Postgres Ready"')
    migration_complete = text.index('log "Migration Complete"')
    app_rollout = text.index('log "Application rollout begins"')
    apply_app = text.index('kubectl apply -k "${APP_OVERLAY}"')
    apply_bootstrap = text.index('kubectl apply -k "${BOOTSTRAP_OVERLAY}"')
    apply_migrate = text.index('kubectl apply -k "${MIGRATE_OVERLAY}"')
    assert apply_bootstrap < postgres_ready < apply_migrate < migration_complete
    assert migration_complete < app_rollout < apply_app
    for line in text.splitlines():
        if "wait_job stockviz-migrate" in line:
            assert "|| true" not in line


def test_shared_base_kustomization_is_namespace_and_config_only() -> None:
    """Bootstrap includes ``../../../base``. That directory must not start apps."""
    text = (K8S / "base" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "namespace.yaml" in text
    assert "configmap.yaml" in text
    assert "app/" not in text
    assert "migrate/" not in text
    assert "scale/" not in text
    assert "deployment" not in text.lower()


def test_bootstrap_overlay_does_not_include_application_workloads() -> None:
    bootstrap = (K8S / "overlays" / "kind" / "bootstrap" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    assert "../../../base/app" not in bootstrap
    assert "../../../base/migrate" not in bootstrap
    assert "../../../base/scale" not in bootstrap
    assert "postgres.yaml" in bootstrap
    # kustomize LoadRestrictionsRootOnly: only a kustomization *directory*
    # may live outside this folder. Raw ``../foo.yaml`` paths fail CI.
    assert "../postgres.yaml" not in bootstrap
    migrate = (K8S / "overlays" / "kind" / "migrate" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    assert "../../../base/migrate" in migrate
    assert "../../../base/app" not in migrate
    app = (K8S / "overlays" / "kind" / "app" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "../../../base/app" in app


def test_migrate_job_is_one_shot_alembic() -> None:
    text = (K8S / "base" / "migrate" / "migrate-job.yaml").read_text(encoding="utf-8")
    assert "restartPolicy: Never" in text
    assert "backoffLimit: 4" in text
    assert "alembic" in text
    assert "upgrade" in text
    assert "head" in text
    assert "|| true" not in text
    assert "stockviz-db" in text
    assert "ANTHROPIC_API_KEY" not in text


def test_workloads_do_not_mount_the_monolithic_secret() -> None:
    for path in (K8S / "base" / "app").glob("*-deployment.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "stockviz-secrets" not in text
        assert "secretRef:" not in text
    bench = (K8S / "benchmark" / "consumer-deployment.yaml").read_text(encoding="utf-8")
    assert "stockviz-secrets" not in bench
    assert "secretKeyRef" not in bench


def test_each_workload_receives_only_its_secrets() -> None:
    for filename, allowed in APP_DEPLOY_FILES.items():
        text = (K8S / "base" / "app" / filename).read_text(encoding="utf-8")
        assert _secret_names(text) == allowed
        if filename != "market-ingest-deployment.yaml":
            assert "ALPHA_VANTAGE_KEY" not in text
        if filename != "news-ingest-deployment.yaml":
            assert "NEWSDATA_KEY" not in text
        if filename != "news-sentiment-deployment.yaml":
            assert "ANTHROPIC_API_KEY" not in text
        if filename not in {"api-deployment.yaml", "web-deployment.yaml"}:
            assert "INTERNAL_API_TOKEN" not in text
            assert "AUTH_SECRET" not in text
        if filename != "web-deployment.yaml":
            assert "AUTH_SECRET" not in text


def test_kind_secrets_are_marked_local_only() -> None:
    for name in (
        "secret-db.yaml",
        "secret-auth.yaml",
        "secret-market.yaml",
        "secret-news.yaml",
        "secret-sentiment.yaml",
    ):
        text = (K8S / "overlays" / "kind" / "bootstrap" / name).read_text(encoding="utf-8")
        assert "kind-dev-only" in text
        assert "stockviz.io/warning" in text
