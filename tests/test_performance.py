"""
Performance Tests - Load testing and benchmarking.

Tests system performance under load using locust.

Usage:
    # Install locust
    pip install locust

    # Run load test
    locust -f tests/test_performance.py --host=http://localhost:8000

    # Run headless with specific user count
    locust -f tests/test_performance.py --host=http://localhost:8000 \
           --users 100 --spawn-rate 10 --run-time 5m --headless
"""

from locust import HttpUser, task, between, constant
import random
import json


class APIUser(HttpUser):
    """
    Simulated user for load testing.

    Simulates realistic usage patterns:
    - Create sessions
    - Create jobs
    - Call LLM API
    - Query audit logs
    """

    # Wait time between tasks (seconds)
    wait_time = between(1, 3)

    def on_start(self):
        """
        Called when user starts.

        Setup: authenticate and get token.
        """
        # In real scenario, authenticate here
        # For now, use mock auth
        self.token = "mock_token"
        self.session_id = None
        self.user_id = f"test_user_{random.randint(1, 10000)}"

    @task(3)
    def create_session(self):
        """Create a new session (high frequency)."""
        payload = {
            "user_id": self.user_id,
            "objective": f"Load test objective {random.randint(1, 1000)}",
            "llm_id": "claude-3-haiku-20240307",
            "llm_version": "20240307",
            "title": f"Load Test Session {random.randint(1, 1000)}"
        }

        with self.client.post(
            "/api/sessions",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                self.session_id = data.get("session_id")
                response.success()
            else:
                response.failure(f"Failed to create session: {response.text}")

    @task(2)
    def list_sessions(self):
        """List sessions (medium frequency)."""
        with self.client.get(
            "/api/sessions",
            params={"limit": 10},
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to list sessions: {response.text}")

    @task(3)
    def create_job(self):
        """Create a job (high frequency)."""
        if not self.session_id:
            return

        job_types = ["llm_call", "data_processing", "report_generation"]

        payload = {
            "session_id": self.session_id,
            "job_type": random.choice(job_types),
            "payload": {
                "test": "data",
                "value": random.randint(1, 100)
            },
            "timeout_seconds": 60
        }

        with self.client.post(
            "/api/jobs",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to create job: {response.text}")

    @task(2)
    def list_jobs(self):
        """List jobs (medium frequency)."""
        with self.client.get(
            "/api/jobs",
            params={"limit": 20},
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to list jobs: {response.text}")

    @task(1)
    def call_llm(self):
        """Call LLM API (low frequency - expensive)."""
        if not self.session_id:
            return

        payload = {
            "session_id": self.session_id,
            "model": "claude-3-haiku-20240307",
            "messages": [
                {
                    "role": "user",
                    "content": f"Test message {random.randint(1, 1000)}"
                }
            ],
            "max_tokens": 50
        }

        with self.client.post(
            "/api/llm/call",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 429:
                # Rate limited - expected
                response.success()
            else:
                response.failure(f"Failed to call LLM: {response.text}")

    @task(1)
    def query_audit_logs(self):
        """Query audit logs (low frequency)."""
        if not self.session_id:
            return

        with self.client.get(
            f"/api/audit/events",
            params={
                "session_id": self.session_id,
                "limit": 50
            },
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to query audit: {response.text}")

    @task(1)
    def health_check(self):
        """Health check (low frequency)."""
        with self.client.get(
            "/health",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("status") in ["healthy", "degraded"]:
                    response.success()
                else:
                    response.failure(f"System unhealthy: {data}")
            else:
                response.failure(f"Health check failed: {response.text}")


class ReadOnlyUser(HttpUser):
    """
    Read-only user for stress testing read operations.

    Only performs GET requests.
    """

    wait_time = constant(0.5)  # Faster than regular users

    @task(5)
    def list_sessions(self):
        """List sessions."""
        self.client.get("/api/sessions?limit=20")

    @task(5)
    def list_jobs(self):
        """List jobs."""
        self.client.get("/api/jobs?limit=20")

    @task(3)
    def health_check(self):
        """Health check."""
        self.client.get("/health")

    @task(2)
    def readiness_check(self):
        """Readiness check."""
        self.client.get("/ready")


class WriteHeavyUser(HttpUser):
    """
    Write-heavy user for testing write performance.

    Focuses on create/update operations.
    """

    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.session_id = None
        self.user_id = f"write_user_{random.randint(1, 10000)}"

    @task(10)
    def create_session(self):
        """Create sessions rapidly."""
        payload = {
            "user_id": self.user_id,
            "objective": f"Write test {random.randint(1, 10000)}",
            "llm_id": "claude-3-haiku-20240307",
            "llm_version": "20240307"
        }
        response = self.client.post("/api/sessions", json=payload)
        if response.status_code == 200:
            self.session_id = response.json().get("session_id")

    @task(10)
    def create_job(self):
        """Create jobs rapidly."""
        if not self.session_id:
            return

        payload = {
            "session_id": self.session_id,
            "job_type": "data_processing",
            "payload": {"data": f"test_{random.randint(1, 10000)}"}
        }
        self.client.post("/api/jobs", json=payload)


# ==============================================================================
# BENCHMARK TESTS
# ==============================================================================

if __name__ == "__main__":
    """
    Run benchmark tests without locust.

    Tests individual operations for baseline performance.
    """
    import time
    import requests
    import statistics

    BASE_URL = "http://localhost:8000"

    def benchmark_endpoint(name: str, method: str, endpoint: str, payload: dict = None, iterations: int = 100):
        """Benchmark a single endpoint."""
        print(f"\n{'='*60}")
        print(f"Benchmarking: {name}")
        print(f"{'='*60}")

        latencies = []

        for i in range(iterations):
            start = time.time()

            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}")
            elif method == "POST":
                response = requests.post(f"{BASE_URL}{endpoint}", json=payload)

            latency_ms = (time.time() - start) * 1000
            latencies.append(latency_ms)

            if response.status_code not in [200, 201]:
                print(f"  ❌ Request {i+1} failed: {response.status_code}")

        # Calculate statistics
        avg = statistics.mean(latencies)
        median = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18]  # 95th percentile
        p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile
        min_lat = min(latencies)
        max_lat = max(latencies)

        print(f"  Iterations: {iterations}")
        print(f"  Average:    {avg:.2f} ms")
        print(f"  Median:     {median:.2f} ms")
        print(f"  P95:        {p95:.2f} ms")
        print(f"  P99:        {p99:.2f} ms")
        print(f"  Min:        {min_lat:.2f} ms")
        print(f"  Max:        {max_lat:.2f} ms")

    # Run benchmarks
    print("\n🚀 Starting Performance Benchmarks\n")

    benchmark_endpoint(
        "Health Check",
        "GET",
        "/health",
        iterations=100
    )

    benchmark_endpoint(
        "List Sessions",
        "GET",
        "/api/sessions?limit=10",
        iterations=50
    )

    benchmark_endpoint(
        "Create Session",
        "POST",
        "/api/sessions",
        payload={
            "user_id": "benchmark_user",
            "objective": "Benchmark test",
            "llm_id": "claude-3-haiku-20240307",
            "llm_version": "20240307"
        },
        iterations=50
    )

    print(f"\n{'='*60}")
    print("✅ Benchmarks Complete")
    print(f"{'='*60}\n")
