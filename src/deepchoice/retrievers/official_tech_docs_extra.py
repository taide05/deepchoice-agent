"""Curated official documentation roots for the 2026-10 formal case technology set.

The base mapping in `official.py` covers the older seed set. These entries give
the 200-case technology names a discovery root; a mapping entry only proposes a
URL. The safe fetch, prose admission and body identity check still decide whether
the page becomes evidence, so a stale or redirecting URL fails visibly instead of
being cited.

Keys use the same normalization as the base mapping: lowercase with punctuation
and spaces removed.
"""

_RAW = {
    "ASP.NET Core": "https://learn.microsoft.com/en-us/aspnet/core/",
    "AWS CDK": "https://docs.aws.amazon.com/cdk/",
    "ActiveMQ": "https://activemq.apache.org/components/classic/documentation",
    "Actix Web": "https://actix.rs/docs/",
    "Airbyte": "https://docs.airbyte.com/",
    "Argo Rollouts": "https://argo-rollouts.readthedocs.io/en/stable/",
    "Auth0": "https://auth0.com/docs",
    "Authentik": "https://docs.goauthentik.io/",
    "Axum": "https://docs.rs/axum/latest/axum/",
    "Buildah": "https://buildah.io/",
    "Buildkite": "https://buildkite.com/docs",
    "CRI-O": "https://cri-o.io/",
    "Calico": "https://docs.tigera.io/calico/latest/about",
    "Cassandra": "https://cassandra.apache.org/doc/latest/",
    "Cilium": "https://docs.cilium.io/en/stable/",
    "CircleCI": "https://circleci.com/docs/",
    "CockroachDB": "https://www.cockroachlabs.com/docs/",
    "Consul": "https://developer.hashicorp.com/consul/docs",
    "Couchbase": "https://docs.couchbase.com/",
    "Dagster": "https://docs.dagster.io/",
    "Deno": "https://docs.deno.com/",
    "Dependabot": "https://docs.github.com/en/code-security/dependabot",
    "Drone": "https://docs.drone.io/",
    "Echo": "https://echo.labstack.com/docs",
    "Envoy": "https://www.envoyproxy.io/docs/envoy/latest/",
    "Fivetran": "https://fivetran.com/docs",
    "Flake8": "https://flake8.pycqa.org/en/latest/",
    "Fluent Bit": "https://docs.fluentbit.io/manual/",
    "Flutter": "https://docs.flutter.dev/",
    "GitLab CI": "https://docs.gitlab.com/ee/ci/",
    "Go Fiber": "https://docs.gofiber.io/",
    "HAProxy": "https://docs.haproxy.org/",
    "Hapi": "https://hapi.dev/tutorials/",
    "Haystack": "https://docs.haystack.deepset.ai/docs/intro",
    "InfluxDB": "https://docs.influxdata.com/influxdb/",
    "Jaeger": "https://www.jaegertracing.io/docs/",
    "Kaniko": "https://github.com/GoogleContainerTools/kaniko#readme",
    "Keycloak": "https://www.keycloak.org/documentation",
    "Koa": "https://koajs.com/",
    "MLflow": "https://mlflow.org/docs/latest/index.html",
    "MariaDB": "https://mariadb.com/kb/en/documentation/",
    "NestJS": "https://docs.nestjs.com/",
    "New Relic": "https://docs.newrelic.com/",
    "Nomad": "https://developer.hashicorp.com/nomad/docs",
    "OpenSearch": "https://opensearch.org/docs/latest/",
    "OpenTofu": "https://opentofu.org/docs/",
    "Ory": "https://www.ory.sh/docs",
    "Phoenix": "https://hexdocs.pm/phoenix/overview.html",
    "Poetry": "https://python-poetry.org/docs/",
    "Pulsar": "https://pulsar.apache.org/docs/",
    "Pydantic v2": "https://docs.pydantic.dev/latest/",
    "Qwik": "https://qwik.dev/docs/",
    "Rails": "https://guides.rubyonrails.org/",
    "React Native": "https://reactnative.dev/docs/getting-started",
    "Redpanda": "https://docs.redpanda.com/",
    "Renovate": "https://docs.renovatebot.com/",
    "Ruff": "https://docs.astral.sh/ruff/",
    "SOPS": "https://getsops.io/docs/",
    "SQLMesh": "https://sqlmesh.readthedocs.io/en/stable/",
    "ScyllaDB": "https://docs.scylladb.com/",
    "SolidJS": "https://docs.solidjs.com/",
    "Spinnaker": "https://spinnaker.io/docs/",
    "Spring Boot": "https://docs.spring.io/spring-boot/index.html",
    "SvelteKit": "https://svelte.dev/docs/kit",
    "Tekton": "https://tekton.dev/docs/",
    "Text Generation Inference": "https://huggingface.co/docs/text-generation-inference/index",
    "TimescaleDB": "https://docs.timescale.com/",
    "Vault": "https://developer.hashicorp.com/vault/docs",
    "Vector": "https://vector.dev/docs/",
    "Weights & Biases": "https://docs.wandb.ai/",
    "YugabyteDB": "https://docs.yugabyte.com/",
    "Zipkin": "https://zipkin.io/pages/quickstart.html",
    "containerd": "https://containerd.io/docs/",
    "dbt": "https://docs.getdbt.com/",
    "etcd": "https://etcd.io/docs/",
    "msgspec": "https://jcristharif.com/msgspec/",
    "pgvector": "https://github.com/pgvector/pgvector",
    "uv": "https://docs.astral.sh/uv/",
}


def _key(name: str) -> str:
    # Keep the word separators: the mapping lookup compares token sequences, so
    # 'asp.net core' matches the candidate tokens 'asp'/'net'/'core'.
    return " ".join(name.lower().split())


EXTRA_TECH_DOCS = {
    _key(name): {"url": url, "title": f"{name} — Official Documentation"}
    for name, url in _RAW.items()
}
