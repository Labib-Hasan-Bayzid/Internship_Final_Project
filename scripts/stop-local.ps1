$ErrorActionPreference = "SilentlyContinue"
kubectl delete namespace dcv-runs --ignore-not-found
kubectl delete deployment frontend backend -n dcv --ignore-not-found
