PY ?= ../AstrBot/.venv/bin/python

.PHONY: help test web-test build dev seed verify e2e

help:
	@echo "make test      # 后端 pytest"
	@echo "make web-test  # 前端 vitest"
	@echo "make build     # 构建控制台到 web/dist"
	@echo "make dev       # 启动独立 dev server (127.0.0.1:6180)"
	@echo "make seed      # 创建管理员/示例模板/邀请码"
	@echo "make verify    # 全部检查（需要 dev server 在跑）"
	@echo "make e2e       # Playwright 浏览器验收"

test:
	$(PY) -m pytest -q

web-test:
	cd web && npm run test

build:
	cd web && npm run build

dev:
	$(PY) scripts/dev_server.py --data-dir devdata --port 6180

seed:
	$(PY) scripts/seed_admin.py --data-dir devdata --invite

verify:
	bash scripts/verify.sh

e2e:
	cd tests/e2e && npx playwright test
