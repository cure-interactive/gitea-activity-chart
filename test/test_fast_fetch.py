from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gitea_activity_chart", ROOT / "gitea-activity-chart.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeSigner:
  public_blob = b"test-public-key"

  def sign(self, data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


class FastFetchTests(unittest.TestCase):
  def test_rapid_ssh_requests_have_distinct_signed_request_ids(self) -> None:
    auth = MODULE.SshSignatureAuth.__new__(MODULE.SshSignatureAuth)
    auth._signer = FakeSigner()
    auth._lock = threading.Lock()
    auth._key_id = "test-key"
    requests = [
      MODULE.requests.Request("GET", "https://gitea.example/api/v1/user").prepare()
      for _ in range(2)
    ]

    started = time.perf_counter()
    for request in requests:
      auth(request)
    elapsed = time.perf_counter() - started

    self.assertLess(elapsed, 0.5)
    self.assertNotEqual(requests[0].headers["X-Request-Id"], requests[1].headers["X-Request-Id"])
    self.assertNotEqual(requests[0].headers["Signature"], requests[1].headers["Signature"])
    self.assertIn("x-request-id", requests[0].headers["Signature"])

  def test_batch_fetch_runs_concurrently_and_preserves_daily_results(self) -> None:
    client = MODULE.GiteaClient.__new__(MODULE.GiteaClient)
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_fetch(*, username, day, page_limit, only_performed_by):
      nonlocal active, maximum_active
      with lock:
        active += 1
        maximum_active = max(maximum_active, active)
      time.sleep(0.02)
      with lock:
        active -= 1
      return day.day

    client.count_user_activity_for_day = fake_fetch
    days = [dt.date(2026, 1, day) for day in range(1, 13)]
    progress = []
    results = client.count_user_activity_for_days(
      username="tester",
      days=days,
      page_limit=50,
      only_performed_by=True,
      max_workers=4,
      progress_callback=lambda completed, total, day, count: progress.append((completed, total, day, count)),
    )

    self.assertGreaterEqual(maximum_active, 2)
    self.assertEqual(results, {day: day.day for day in days})
    self.assertEqual(len(progress), len(days))
    self.assertEqual({entry[2] for entry in progress}, set(days))


if __name__ == "__main__":
  unittest.main()
