.PHONY: up down migrate-up migrate-down migrate-check test seed-demo seed-full check-telegram demo-ready prepare-staging-env setup-gh-secrets local-ready

up:
	docker compose up --build -d

down:
	docker compose down

migrate-up:
	docker compose run --rm api alembic upgrade head

migrate-down:
	docker compose run --rm api alembic downgrade base

migrate-check:
	docker compose run --rm api sh -lc "alembic upgrade head && alembic downgrade base && alembic upgrade head"

test:
	python3 -m pytest -q

seed-demo:
	PYTHONPATH=. POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 python3 scripts/seed_demo_data.py

seed-full:
	PYTHONPATH=. POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 python3 scripts/seed_full_demo_data.py

check-telegram:
	PYTHONPATH=. python3 scripts/check_telegram_setup.py

prepare-staging-env:
	python3 scripts/prepare_staging_env.py

demo-ready:
	PYTHONPATH=. python3 scripts/check_demo_ready.py

setup-gh-secrets:
	bash scripts/setup_github_secrets.sh

local-ready:
	python3 -m ruff check app tests scripts
	python3 -m pytest -q
	$(MAKE) migrate-check
	docker compose restart api bot worker
	$(MAKE) seed-demo
	$(MAKE) check-telegram
	$(MAKE) demo-ready
