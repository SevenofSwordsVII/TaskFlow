# TaskFlow Load Testing with Locust

This directory contains the automated performance and load testing suite for the TaskFlow SaaS API using [Locust](https://locust.io/).

---

## 1. Directory Structure

```text
loadtests/
├── locustfile.py           # Realistic user scenarios, Kanban workflows, admin actions, and negative tests
├── test_route_inventory.py # Automated route audit comparing registered FastAPI routes with inventory
├── route_coverage.md       # Comprehensive 43-route coverage and disposition matrix
└── README.md               # Execution instructions, performance profiles, and configurations
```

---

## 2. Configuration & Environment Variables

| Variable | Description | Default |
|:---|:---|:---|
| `LOCUST_HOST` | Target TaskFlow API base URL | `http://localhost:8000` (or `http://backend:8000` in Docker) |
| `LOADTEST_PASSWORD` | Password assigned to dynamically registered test users | `LoadTestPass123!Secure` |
| `LOADTEST_USER_PREFIX` | Prefix used for disposable test account emails | `lt_user` |

---

## 3. Performance Profiles

### A. Smoke Test Profile (Pre-flight Validation)
- **Users**: 2 concurrent users
- **Spawn rate**: 1 user/sec
- **Duration**: 30 seconds
- **Purpose**: Verify endpoint reachability, authentication lifecycle, and zero errors before scaling up.

```bash
# Docker Compose
docker compose run --rm locust locust -f /loadtests/locustfile.py --headless -u 2 -r 1 --run-time 30s --host http://backend:8000 --tags smoke

# Local Execution
locust -f loadtests/locustfile.py --headless -u 2 -r 1 --run-time 30s --host http://localhost:8000 --tags smoke
```

### B. Baseline Performance Profile
- **Users**: 10 concurrent users
- **Spawn rate**: 2 users/sec
- **Duration**: 2 minutes
- **Purpose**: Measure p50, p95, and p99 response times under light steady-state traffic.

```bash
# Docker Compose
docker compose run --rm locust locust -f /loadtests/locustfile.py --headless -u 10 -r 2 --run-time 2m --host http://backend:8000 --csv=/loadtests/results/baseline

# Local Execution
locust -f loadtests/locustfile.py --headless -u 10 -r 2 --run-time 2m --host http://localhost:8000 --csv=loadtests/results/baseline
```

### C. Normal Load Test Profile
- **Users**: 50 concurrent users
- **Spawn rate**: 5 users/sec
- **Duration**: 5 minutes
- **Purpose**: Validate Kanban OCC concurrency, horizontal list moving, database connection pools, and caching.

```bash
# Docker Compose
docker compose run --rm locust locust -f /loadtests/locustfile.py --headless -u 50 -r 5 --run-time 5m --host http://backend:8000 --csv=/loadtests/results/load

# Local Execution
locust -f loadtests/locustfile.py --headless -u 50 -r 5 --run-time 5m --host http://localhost:8000 --csv=loadtests/results/load
```

### D. Stress Test Profile (Opt-in)
- **Users**: 150+ concurrent users
- **Spawn rate**: 10 users/sec
- **Duration**: 10 minutes
- **Purpose**: Determine server saturation point and verify graceful degradation without database connection leaks.

---

## 4. Interactive Web UI

To run Locust with its browser-based real-time dashboard:

```bash
# Start Locust container in Docker Compose
docker compose up -d locust

# Open your browser at:
# http://localhost:8089
```

Enter host `http://backend:8000` (or leave default), set user count, and click **Start Swarming**.

---

## 5. Automated Route Audit Check

Run `test_route_inventory.py` to assert that every route in the FastAPI application is accounted for:

```bash
docker compose run --rm backend python /loadtests/test_route_inventory.py
```

---

## 6. Data Hygiene & Safety Rules

1. **Dedicated Disposable Namespaces**: All users are prefixed with `LOADTEST_USER_PREFIX` (`lt_user_...`) and isolated to their own generated organizations (`Workspace ...`).
2. **Bounded Resource Creation**:
   - Tasks and comments created in high-frequency tasks are updated and soft-deleted within the same iteration to prevent database bloat.
   - Invitations created during admin tests are immediately revoked after creation and listing.
3. **Optimistic Concurrency Control (OCC)**:
   - Concurrent moves on the same task or list returning `409 Conflict` (`TASK_VERSION_CONFLICT`) are validated as normal OCC behavior under load and recorded as valid responses.
4. **Session Teardown**:
   - `on_stop` handlers invoke `POST /api/v1/auth/logout` to revoke session tokens cleanly.
