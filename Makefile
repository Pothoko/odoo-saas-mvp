COMPOSE = docker compose -f docker-compose.dev.yml

.PHONY: dev-kubeconfig dev-clone-deps dev-up dev-down dev-reset \
        dev-install dev-rebuild-portal dev-logs logs-odoo logs-portal \
        logs-postgres dev-psql odoo-shell portal-shell help

dev-kubeconfig: ## Genera k3s-docker.yaml con host.docker.internal para el portal
	@mkdir -p ~/.kube
	@sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/k3s-docker.yaml
	@sudo chown $(USER):$(USER) ~/.kube/k3s-docker.yaml
	@sed -i 's|https://127.0.0.1|https://host.docker.internal|g' ~/.kube/k3s-docker.yaml
	@echo "OK: ~/.kube/k3s-docker.yaml listo"

dev-clone-deps: ## Clona addons externos (subscription_oca) en ./vendor/
	@mkdir -p vendor
	@if [ ! -d vendor/subscription_oca ]; then \
		git clone --depth=1 -b 18.0 https://github.com/jpvargassoruco/odoo18-oca-contract.git /tmp/oca-tmp && \
		cp -r /tmp/oca-tmp/subscription_oca vendor/ && \
		rm -rf /tmp/oca-tmp && \
		echo "OK: vendor/subscription_oca clonado"; \
	else \
		echo "INFO: vendor/subscription_oca ya existe, omitiendo"; \
	fi

dev-up: ## Levanta postgres + odoo + portal
	$(COMPOSE) up -d
	@echo ""
	@echo "Servicios arriba:"
	@echo "  Odoo Admin : http://localhost:18069"
	@echo "  Portal API : http://localhost:8000/docs"
	@echo "  API Key    : dev-api-key-local"

dev-down: ## Para los contenedores (datos se conservan)
	$(COMPOSE) down

dev-reset: ## Para + borra volumenes (BD limpia desde cero)
	$(COMPOSE) down -v
	@echo "OK: Volumenes eliminados."

dev-rebuild-portal: ## Rebuilda la imagen del portal (si cambias requirements.txt)
	$(COMPOSE) build portal
	$(COMPOSE) up -d portal

dev-install: ## Instala/actualiza todos los modulos Odoo
	$(COMPOSE) exec odoo odoo \
		-i odoo_k8s_saas,odoo_k8s_saas_subscription,payment_qr_mercantil,subscription_oca \
		-d admin --stop-after-init --no-http
	$(COMPOSE) restart odoo

dev-logs: ## Logs de todos los servicios
	$(COMPOSE) logs -f

logs-odoo: ## Logs solo de Odoo
	$(COMPOSE) logs -f odoo

logs-portal: ## Logs solo del Portal
	$(COMPOSE) logs -f portal

logs-postgres: ## Logs solo de Postgres
	$(COMPOSE) logs -f postgres

odoo-shell: ## Bash en el contenedor Odoo
	$(COMPOSE) exec odoo bash

portal-shell: ## Bash en el contenedor Portal
	$(COMPOSE) exec portal bash

dev-psql: ## psql en Postgres (base admin)
	$(COMPOSE) exec postgres psql -U odoo -d admin

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
