# All logic lives in scripts/tasks.py so it also works without make.
# Usage: make setup | make lint test | make eval [C=kpi_extractor] | make app
.RECIPEPREFIX = >

ifeq ($(OS),Windows_NT)
PY ?= py
else
PY ?= python3
endif

TASKS = $(PY) scripts/tasks.py

.PHONY: setup lint format test eval app

setup:
> $(TASKS) setup

lint:
> $(TASKS) lint

format:
> $(TASKS) format

test:
> $(TASKS) test

eval:
> $(TASKS) $(if $(C),eval:$(C),eval)

app:
> $(TASKS) app
