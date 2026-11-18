# Load test summary

Machine: GitHub Actions ubuntu-latest, 4 vCPU, 15Gi

Constant rate: p50 10.58 ms, p95 50.95 ms, p99 137.63 ms, errors 0.00%, 100.0 req/s, 6001 requests

| target rps | achieved rps | p50 ms | p95 ms | errors | ok |
|---|---|---|---|---|---|
| 100 | 100.0 | 10.6 | 53.15 | 0.00% | yes |
| 120 | 120.0 | 13.81 | 119.79 | 0.00% | yes |
| 140 | 140.0 | 13.01 | 23.86 | 0.00% | yes |
| 160 | 160.0 | 14.98 | 95.29 | 0.00% | yes |
| 180 | 180.0 | 14.07 | 41.51 | 0.00% | yes |
| 200 | 200.0 | 19.15 | 82.93 | 0.00% | yes |
| 250 | 175.7 | 930.29 | 2115.35 | 0.68% | no |

Max transfers/sec meeting the criteria: 200

Retry storm: {"unique_keys": 1201, "requests_sent": 6005, "transfers_created": 1201, "duplicate_transfers": 0}

Ledger check: ok=True, drift=0
