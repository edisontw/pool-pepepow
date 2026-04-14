# Tests

Current coverage is intentionally small and focused on the MVP skeleton:

- API endpoint availability
- wallet validation behavior
- snapshot error handling
- producer runtime snapshot generation
- local share ingest parsing
- activity accounting aggregation
- stratum ingress and activity snapshot generation
- atomic JSON snapshot writes

Run:

```bash
cd /home/ubuntu/pool-pepepow
python3 -m unittest discover tests
```
