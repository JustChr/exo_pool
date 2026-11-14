# Contributing

## Prerequisites

- Docker
- Python 3.14+ (Home Assistant's minimum)
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
pip install pytest awsiotsdk
python3 -m pytest tests/ -v
```

This runs the MQTT client tests, which need no Home Assistant installation.

To also run the Home Assistant integration tests (`tests/test_setup.py` — setup/unload,
entities, climate, config flow, re-auth), install the HA test harness. It only works on
Linux/macOS (or WSL); on Windows these tests are skipped automatically:

```bash
pip install pytest-homeassistant-custom-component awsiotsdk
python3 -m pytest tests/ -v
```

CI (`.github/workflows/tests.yml`) runs the full suite on every push and pull request.
