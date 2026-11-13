# Atalhos. No Windows sem `make`, use run.bat (ex.: run.bat qr) ou
# `python niimparty.py <comando>`.

ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
  SYS_PY  := python
else
  VENV_PY := .venv/bin/python
  SYS_PY  := python3
endif

.PHONY: run setup qr preview validate test install

run: install
	$(VENV_PY) niimparty.py run

setup: install
	$(VENV_PY) niimparty.py setup

qr: install
	$(VENV_PY) niimparty.py qr

preview: install
	$(VENV_PY) niimparty.py preview

validate: install
	$(VENV_PY) niimparty.py validate

test: install
	$(VENV_PY) niimparty.py test

install: .venv/.installed

.venv/.installed: requirements.txt
	$(SYS_PY) -m venv .venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r requirements.txt
	@echo ok > .venv/.installed
