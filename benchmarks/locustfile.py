"""Read-only HTTP smoke load; does not measure research throughput or quality."""
from locust import HttpUser, between, task


class DeepChoiceUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def health_check(self):
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code != 200 or resp.json().get("status") != "ok":
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(1)
    def swagger_docs(self):
        with self.client.get("/docs", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"Swagger docs failed: {resp.status_code}")

    @task(1)
    def task_status(self):
        with self.client.get("/api/v1/tasks/nonexistent", catch_response=True) as resp:
            if resp.status_code != 404:
                resp.failure(f"Unexpected status: {resp.status_code}")
            else:
                resp.success()  # Locust otherwise counts an expected 404 as failure.
