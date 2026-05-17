# Contributing

## Prerequisites

- Docker
- Python 3.9+
- A Zodiac iAqualink account with an Exo device

## Quick start

```bash
git clone https://github.com/JustChr/exo_pool.git
cd exo_pool

echo "EXO_EMAIL=your@email.com" > .env
echo "EXO_PASSWORD=yourpassword" >> .env

make dev
# Open http://localhost:8125  (login: dev / devdevdev)
```

## Useful commands

```bash
make test       # run unit + integration tests
make logs       # tail the HA container logs
make restart    # restart HA after code changes
make stop       # stop the container
```

## Running tests

```bash
pip install pytest pytest-asyncio awsiotsdk
python3 -m pytest tests/ -v
```

Tests are isolated from Home Assistant — no HA installation required.
