#!/usr/bin/env python3
"""
loadtest.py — "the deep freeze hits Kansas City." Standard library only, runs in Cloud Shell as-is.

Usage:
  python3 loadtest.py URL [-n REQUESTS] [-c CONCURRENCY] [--token TOKEN]

  URL           service base URL, e.g. https://plumbing-agent-xxxx.a.run.app
  -n            total requests            (default 20)
  -c            requests in flight at once (default 10)
  --token       identity token for a private Cloud Run service
                (in Cloud Shell: --token "$(gcloud auth print-identity-token)")

It reports three kinds of outcome, because they mean three different things:
  200            served
  429 upstream   the MODEL PROVIDER is rate-limiting us  (fix: quota, backoff, queue, gateway)
  429 platform   CLOUD RUN had no free instance          (fix: --concurrency / --max-instances)
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

MESSAGES = [
    "Pipe burst in my basement. Need 40 of the 3/4 inch PEX elbows and a 100 ft roll of 3/4 red PEX. When can I get them?",
    "Price on 120 half-inch crimp tees?",
    "Do you have heat tape? Need 3 for a crawl space.",
    "Need 2 bags of 1/2 crimp rings and a crimp tool.",
    "How much for 60 of the 3/4 push-to-connect couplings?",
    "Got any 1 inch copper sweat elbows?",
    "Looking for 300 feet of foam insulation for 1/2 inch pipe.",
    "Need a 3/4 ball valve and 10 of the 3/4 tees.",
]


def one_request(i: int, url: str, token: str | None) -> dict:
    body = json.dumps({"message": MESSAGES[i % len(MESSAGES)]}).encode()
    req = urllib.request.Request(f"{url.rstrip('/')}/quote", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
            return {"outcome": "200", "ms": (time.perf_counter() - t0) * 1000,
                    "tokens": data.get("input_tokens", 0) + data.get("output_tokens", 0),
                    "revision": data.get("revision")}
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        if e.code == 429:
            outcome = "429 upstream" if "upstream_rate_limit" in text else "429 platform"
        else:
            outcome = str(e.code)
        return {"outcome": outcome, "ms": (time.perf_counter() - t0) * 1000, "tokens": 0}
    except Exception as e:  # timeouts, connection resets
        return {"outcome": type(e).__name__, "ms": (time.perf_counter() - t0) * 1000, "tokens": 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("-c", type=int, default=10)
    p.add_argument("--token")
    a = p.parse_args()

    print(f"Firing {a.n} requests, {a.c} at a time, at {a.url} ...")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.c) as pool:
        results = list(pool.map(lambda i: one_request(i, a.url, a.token), range(a.n)))
    wall = time.perf_counter() - t0

    counts = Counter(r["outcome"] for r in results)
    ok = [r["ms"] for r in results if r["outcome"] == "200"]
    revisions = {r.get("revision") for r in results if r.get("revision")}

    print(f"\nWall clock: {wall:.1f}s   Throughput: {a.n / wall:.2f} req/s")
    print("Outcomes:  " + "   ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    if ok:
        q = statistics.quantiles(ok, n=20) if len(ok) >= 2 else [ok[0]] * 19
        print(f"Latency (successful):  p50 {statistics.median(ok)/1000:.1f}s   "
              f"p95 {q[18]/1000:.1f}s   max {max(ok)/1000:.1f}s")
    print(f"Tokens used: {sum(r['tokens'] for r in results):,}")
    if revisions:
        print(f"Served by revision(s): {', '.join(sorted(revisions))}")


if __name__ == "__main__":
    main()
