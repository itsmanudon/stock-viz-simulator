# CI uses `scripts/k8s/deploy.sh`, which applies the kind overlay **layers**
# in order (bootstrap → migrate → app → scale). There is no combined
# kustomization that would start application pods before Alembic.
