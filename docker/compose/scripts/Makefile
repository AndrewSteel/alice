SHELL := /bin/bash

# Root deines Stacks
ROOT ?= /srv/compose

# Liste deiner Stacks (Pfad relativ zu $(ROOT))
STACKS ?= \
  infra \
  infra/gotify \
  infra/watchtower \
  infra/kanboard \
  data/database \
  automations/n8n \
  automations/hassil-parser \
  automations/alice-auth \
  automations/mqtt \
  automations/weaviate \
  ai/ollama \
  ai/openwebui \
  ai/whisper \
  ai/piper \
  ai/jupyter

# Optional: s=<stack-pfad>, svc=<servicename>, prune=yes
# Beispiele:
#   make restart s=automations/n8n
#   make update s=ai/ollama-3090 svc=ollama
#   make update prune=yes

.PHONY: up down ps logs app-up app-down restart recreate update update-all pull pull-all health wait prune-old images

networks:
	@echo "Creating networks if not exist..."
# docker compose -f $(ROOT)/infra/networks/compose.yml up -d
# Alternativ direkt über Docker CLI, damit es auch ohne den infra Stack funktioniert:
	@docker network inspect frontend >/dev/null 2>&1 || docker network create frontend
	@docker network inspect backend >/dev/null 2>&1 || docker network create backend
	@docker network inspect automation >/dev/null 2>&1 || docker network create automation
	
up: networks
	@for s in $(STACKS); do \
	  echo ">>> $$s"; \
	  docker compose -f $(ROOT)/$$s/compose.yml up -d --remove-orphans; \
	done

down:
	@for s in $(STACKS); do \
	  echo ">>> $$s"; \
	  docker compose -f $(ROOT)/$$s/compose.yml down; \
	done

ps:
	@for s in $(STACKS); do \
	  echo ">>> $$s"; \
	  docker compose -f $(ROOT)/$$s/compose.yml ps; \
	done

logs:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@docker compose -f $(ROOT)/$(s)/compose.yml logs -f --tail=200 $(svc)

app-up:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@docker compose -f $(ROOT)/$(s)/compose.yml up -d --remove-orphans $(svc)

app-down:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@docker compose -f $(ROOT)/$(s)/compose.yml down $(svc)

# Soft-Restart (Signal). Benutzen, wenn ein Dienst hängt, aber keine Konfigänderung vorliegt.
restart:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@echo ">>> restart $(s) $(svc)"
	@docker compose -f $(ROOT)/$(s)/compose.yml restart $(svc)

# Hard-Recreate (sauber für Konfig/Volume-Änderungen)
recreate:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@echo ">>> recreate $(s) $(svc)"
	@docker compose -f $(ROOT)/$(s)/compose.yml up -d --force-recreate --remove-orphans $(svc)
	@$(MAKE) wait s=$(s) svc="$(svc)"

# Update für EINEN Stack oder EINEN Service: pull → up → wait → optional prune
update:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@echo ">>> update $(s) $(svc)"
	@docker compose -f $(ROOT)/$(s)/compose.yml pull $(svc)
	@docker compose -f $(ROOT)/$(s)/compose.yml up -d --no-deps --remove-orphans $(svc)
	@$(MAKE) wait s=$(s) svc="$(svc)"
ifneq ($(prune),)
	@$(MAKE) prune-old
endif

# Update für ALLE Stacks
update-all:
	@for s in $(STACKS); do \
	  echo ">>> update $$s"; \
	  docker compose -f $(ROOT)/$$s/compose.yml pull; \
	  docker compose -f $(ROOT)/$$s/compose.yml up -d --no-deps --remove-orphans; \
	done
	@$(MAKE) wait
ifneq ($(prune),)
	@$(MAKE) prune-old
endif

pull:
	@test -n "$(s)" || (echo "Setze s=<stack-pfad>"; exit 1)
	@docker compose -f $(ROOT)/$(s)/compose.yml pull $(svc)

pull-all:
	@for s in $(STACKS); do \
	  echo ">>> pull $$s"; \
	  docker compose -f $(ROOT)/$$s/compose.yml pull; \
	done

# Health-Check: wartet bis alles healthy oder 60 * 5s
wait:
	@STACK="$(s)"; SVC="$(svc)"; \
	FILE="$(ROOT)/$${STACK}/compose.yml"; \
	if [ -z "$$STACK" ]; then \
	  for st in $(STACKS); do \
	    echo ">>> wait $$st"; \
	    $(MAKE) health s=$$st svc="$(svc)"; \
	  done; \
	else \
	  $(MAKE) health s=$$STACK svc="$$SVC"; \
	fi

health:
	@FILE="$(ROOT)/$(s)/compose.yml"; SVC="$(svc)"; \
	echo ">>> health $(s) $${SVC:-<all>}"; \
	for i in {1..60}; do \
	  UNHEALTHY=$$(docker compose -f $$FILE ps --format json $$SVC \
	    | jq -r '.[] | select(.Health!="healthy" and .State=="running") | .Name' \
	    | wc -l); \
	  STARTING=$$(docker compose -f $$FILE ps --format json $$SVC \
	    | jq -r '.[] | select(.State=="starting") | .Name' \
	    | wc -l); \
	  if [ "$$UNHEALTHY" -eq 0 ] && [ "$$STARTING" -eq 0 ]; then \
	    echo ">>> healthy: $(s) $${SVC:-all}"; exit 0; \
	  fi; \
	  sleep 5; \
	done; \
	echo "!!! timeout: $(s) $${SVC:-all} nicht healthy"; \
	docker compose -f $$FILE ps; \
	exit 1

# Entfernt dangling Images nach Updates
prune-old:
	@docker image prune -f

images:
	@docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}'
