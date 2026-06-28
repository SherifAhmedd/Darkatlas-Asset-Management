# DarkAtlas Asset Management System

Welcome to the **DarkAtlas Asset Management System**, a core module of Buguard's DarkAtlas Attack Surface Monitoring (ASM) platform. 

This repository contains the backend implementation for **Track A (Backend Engineering)**, designed to continuously discover, track, and map relationships between an organization’s internet-facing assets (domains, subdomains, IP addresses, services, and certificates) under a secure multi-tenant model.

---

## 🚀 Quickstart & Setup

This application is fully containerized using **Docker** and **Docker Compose**. You do not need to install Python or PostgreSQL on your host machine to run or test the application.

### Prerequisites
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

### 1. Configure the Environment
Create a `.env` file in the root directory by copying the example:
```bash
copy .env.example .env
```
*(The default credentials are pre-configured to work out-of-the-box with the Docker containers).*

### 2. Start the Docker Stack
Build and launch the application containers (FastAPI app + PostgreSQL database) in the background:
```bash
docker compose up --build -d
```

### 3. Generate and Apply Database Migrations
Migrations are managed via **Alembic**. Run the following commands to initialize the schema:
```bash
# Generate the initial migration script
docker compose run app alembic revision --autogenerate -m "Initial database tables"

# Apply the migrations (created on app container boot automatically, or run manually)
docker compose run app alembic upgrade head
```

### 4. Access the API Documentation
Once the stack is running, open your browser and navigate to:
* **Interactive OpenAPI Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **Alternative ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🛠️ Running the Test Suite

The project includes a comprehensive test suite of **52 async integration tests** written with `pytest` and `pytest-asyncio`. 

The test suite:
1. Automatically spins up an isolated `darkatlas_test` database container.
2. Creates and teardowns tables for each individual test to guarantee complete isolation.
3. Cleanly disposes database connections via a `NullPool` adapter to prevent event loop reuse conflicts.

### Run tests inside Docker:
```bash
docker compose run --remove-orphans app sh -c "pip install -e '.[dev]' -q && pytest -v --tb=short"
```

---

## 🏛️ System Architecture

### Multi-Tenant Isolation
Security is built into the core database layer. Every table (`users`, `assets`, `relationships`) references a `tenant_id` UUID. 
* All database queries, updates, and deletes are scoped strictly to the authenticated tenant injected via dependency.
* Attempting to query, link, or delete assets belonging to another tenant will raise a `404 Not Found` error to prevent resource enumeration.

### Database Schema Details
* **Users / Tenants:** Contains registration details and dynamically assigns a unique `tenant_id` namespace.
* **Assets:** Tracks structural entities like `domain`, `subdomain`, `ip_address`, `service`, and `certificate`. Implements a unique constraint on `(tenant_id, type, value)` to prevent duplicates.
* **Relationships:** Stores directed edges mapping the attack surface graph (e.g. Subdomain of, Certificate covers, Service runs on).

### 5-Stage Import Pipeline Design
The bulk import endpoint (`/api/v1/assets/import`) runs incoming datasets through a structured pipeline:
1. **Validation:** Checks records against Pydantic schemas. Invalid items are recorded as failures; the rest of the batch continues.
2. **Normalization:** Lowercases domain/subdomain names, strips trailing dots, normalizes IP addresses, and lowercases service protocols (e.g. `443/TCP` becomes `443/tcp`).
3. **Deduplication:** Checks existing assets in the DB and matches them. It also resolves normalization duplicates *within the incoming batch itself*.
4. **Merge/Create:** Creates new assets. For existing assets, it implements a **freshness rule** (incoming metadata keys overwrite existing keys while preserving original keys) and a **tag union** (merges tag lists, deduplicates, and sorts them).
5. **Relationships:** Resolves batch-level temporary IDs (e.g. `a1`, `a2`) to database-level UUIDs and inserts directed relationship edges safely.

---

## 📡 API Endpoints

### 🔐 Authentication (`/api/v1/auth`)
* `POST /register`: Registers a new user/tenant and returns a JWT access token.
* `POST /login`: Logs in an existing user and returns a JWT access token.

### 📦 Asset Management (`/api/v1/assets`)
* `POST /`: Create a single asset (409 Conflict if duplicate).
* `GET /`: List assets with filtering (`asset_type`, `status`, `tag`, `value_contains`) and offset-limit pagination.
* `GET /{id}`: Fetch detailed asset information.
* `PUT /{id}`: Update tags/metadata (merges instead of overwrites).
* `DELETE /{id}`: Delete an asset.
* `PATCH /{id}/status`: Transition asset status (e.g. `active` ➔ `stale` ➔ `archived`).
* `POST /import`: Run the 5-Stage bulk import pipeline.
* `GET /{id}/graph`: Returns an adjacency list representation of the asset's direct connections (root node, adjacent nodes, and edges).

### 🔗 Relationship Management (`/api/v1/relationships`)
* `POST /`: Create a typed edge between two assets (`SUBDOMAIN_OF`, `RESOLVES_TO`, `USES`, `RUNS_ON`, `COVERS`).
* `GET /`: List relationships with pagination.
* `DELETE /{id}`: Remove a relationship edge.

---

## 🤖 AI Bonus Feature (Track A - Optional)

An optional AI-driven Risk Scoring feature can be activated to analyze assets and assign dynamic security risk scores based on public exposure metadata (e.g., exposed ports, protocol versions, SSL expiration).