.PHONY: install web dev serve demo test run docker

install:            ## Python + dashboard deps
	pip install -e ".[browser,dev]" && playwright install chromium
	cd web && npm ci

web:                ## build the dashboard into web/dist
	cd web && npm run build

serve: web          ## dashboard + API + scheduler on :8000
	sentinel serve

dev:                ## hot-reload UI on :5173 (proxying the API on :8000)
	(sentinel serve --no-scheduler &) && cd web && npm run dev

demo: web           ## explore the UI with illustrative sample data
	sentinel demo && SENTINEL_DEMO=1 sentinel serve --no-scheduler

run:                ## one collection pass, then exit
	sentinel run && sentinel digest

test:
	pytest -q

docker:
	docker compose up --build -d
