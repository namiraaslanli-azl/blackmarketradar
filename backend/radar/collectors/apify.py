"""Minimal Apify API client: start an actor run, wait for it, read its dataset."""

from __future__ import annotations

import time

import httpx

from radar.collectors.http import client, request
from radar.config import get_settings

BASE = "https://api.apify.com/v2"
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


class ApifyError(RuntimeError):
    pass


class Apify:
    def __init__(self, token: str | None = None, http: httpx.Client | None = None, poll_seconds: float = 10.0,
                 sleep=time.sleep):
        self.token = token or get_settings().apify_token
        self.http = http or client(timeout=60)
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        self.poll_seconds = poll_seconds
        self.sleep = sleep

    def run_actor(self, actor: str, run_input: dict, *, max_items: int | None = None,
                  timeout_s: int = 3600, memory_mb: int | None = None) -> list[dict]:
        params = {"timeout": timeout_s}
        if max_items:
            params["maxItems"] = max_items
        if memory_mb:
            params["memory"] = memory_mb
        r = request(self.http, "POST", f"{BASE}/acts/{actor.replace('/', '~')}/runs", params=params, json=run_input)
        run = r.json()["data"]
        deadline = time.monotonic() + timeout_s + 120
        while run["status"] not in TERMINAL:
            if time.monotonic() > deadline:
                raise ApifyError(f"{actor}: run {run['id']} did not finish in time")
            self.sleep(self.poll_seconds)
            run = request(self.http, "GET", f"{BASE}/actor-runs/{run['id']}", params={"waitForFinish": 60}).json()["data"]
        if run["status"] != "SUCCEEDED":
            raise ApifyError(f"{actor}: run {run['id']} ended {run['status']}")
        return self.dataset_items(run["defaultDatasetId"])

    def dataset_items(self, dataset_id: str, page: int = 1000) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            r = request(self.http, "GET", f"{BASE}/datasets/{dataset_id}/items",
                        params={"clean": "true", "format": "json", "offset": offset, "limit": page})
            chunk = r.json()
            items.extend(chunk)
            if len(chunk) < page:
                return items
            offset += page
