# Quick Start

Prerequisites: Docker, Node.js 18+, Python 3.12+

```bash
# 1. Clone and configure
git clone <repo-url> && cd local_agent_tracker
cp .env.example .env

# 2. Start MySQL + phpMyAdmin
docker compose up -d

# 3. Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev

# 5. Seed sample data (optional, new terminal)
mysql -h 127.0.0.1 -P 23847 -u lat_user -plat_dev_password local_agent_tracker < seed.sql

# 6. Open the dashboard
open http://localhost:5173
```

## Ports

| Service    | Port  |
|------------|-------|
| Frontend   | 5173  |
| API        | 8000  |
| API Docs   | 8000/docs |
| MySQL      | 23847 |
| phpMyAdmin | 8080  |

## Run tests

```bash
cd backend && source .venv/bin/activate
pytest tests/ -v
```

## Scan tokens from transcripts

```bash
POST http://localhost:8000/api/projects/1/scan-tokens
```
