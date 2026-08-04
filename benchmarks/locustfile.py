"""Basic load test for DeepChoice server endpoints."""
from locust import HttpUser, task, between


class DeepChoiceUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def health_check(self):
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code != 200 or resp.json().get("status") != "ok":
                resp.failure(f"Health check failed: {resp.status_code} {resp.text}")

    @task(1)
    def swagger_docs(self):
        with self.client.get("/docs", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"Swagger docs failed: {resp.status_code}")

    @task(1)
    def task_status(self):
        with self.client.get("/research/nonexistent/status", catch_response=True) as resp:
            # Expecting 404 or 200, both are valid responses
            if resp.status_code not in (200, 404):
                resp.failure(f"Unexpected status: {resp.status_code}")
