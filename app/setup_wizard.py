"""Perguntas da primeira execução: gravam config.yaml e .env."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

from . import config as C
from .i18n import available_languages, load_locale
from .printers import DRIVERS, list_profiles, load_profile
from .templates import list_templates, load_template

Ask = Callable[[str], str]


class Wizard:
    def __init__(self, ask: Ask = input, say: Callable[[str], None] = print):
        self.ask_raw = ask
        self.say = say
        self.S: dict[str, str] = load_locale("pt-BR")

    # ------------------------------------------------------------ helpers

    def ask(self, question: str, default: str = "") -> str:
        hint = f" [{default}]" if default else ""
        answer = self.ask_raw(f"{question}{hint}: ").strip()
        return answer or default

    def choose(self, question: str, options: list[str], labels: list[str] | None = None, default: int = 0) -> str:
        labels = labels or options
        self.say(f"\n{question}")
        for i, label in enumerate(labels, 1):
            self.say(f"  {i}) {label}")
        while True:
            answer = self.ask(self.S.get("wiz_choose", "Escolha um número"), str(default + 1))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            if answer in options:
                return answer
            self.say("  ?")

    def yes_no(self, question: str, default: bool) -> bool:
        y, n = self.S["wiz_yes"], self.S["wiz_no"]
        while True:
            answer = self.ask(question, y if default else n).lower()
            if answer[:1] in (y, "y", "s"):
                return True
            if answer[:1] in (n, "n"):
                return False

    # ------------------------------------------------------------ fluxo

    def run(self) -> dict[str, Any]:
        cfg = C.load_config()
        previous_template = cfg.get("template") if C.CONFIG_PATH.exists() else None

        langs = available_languages()
        lang_labels = [load_locale(lng).get("lang_name", lng) for lng in langs]
        default_lang = langs.index("pt-BR") if "pt-BR" in langs else 0
        self.say("\nNiimparty\n=========")
        lang = self.choose("Idioma / Language", langs, lang_labels, default_lang)
        self.S = load_locale(lang)
        S = self.S
        cfg["language"] = lang
        self.say(f"\n{S['wiz_welcome']}\n")

        cfg["event"]["name"] = self.ask(S["wiz_event_name"], cfg["event"].get("name") or "")
        date_fmt = S.get("date_format", "%d/%m/%Y")
        default_date = ""
        if cfg["event"].get("date"):
            try:
                default_date = dt.date.fromisoformat(str(cfg["event"]["date"])).strftime(date_fmt)
            except ValueError:
                pass
        while True:
            raw = self.ask(S["wiz_event_date"], default_date or dt.date.today().strftime(date_fmt))
            try:
                cfg["event"]["date"] = dt.datetime.strptime(raw, date_fmt).date().isoformat()
                break
            except ValueError:
                try:
                    cfg["event"]["date"] = dt.date.fromisoformat(raw).isoformat()
                    break
                except ValueError:
                    self.say(S["wiz_bad_date"])

        templates = list_templates()
        loaded = {t: load_template(t, strict=False) for t in templates}
        labels = [f"{loaded[t].name} — {loaded[t].description}" if loaded[t].description else loaded[t].name
                  for t in templates]
        current = templates.index(cfg["template"]) if cfg["template"] in templates else 0
        tid = self.choose(S["wiz_template"], templates, labels, current)
        cfg["template"] = tid
        tpl = loaded[tid]

        texts = {}
        if tpl.texts:
            self.say(f"\n{S['wiz_texts']}")
            old = cfg.get("texts") or {}
            for spec in tpl.texts:
                default = str(old.get(spec.id, spec.default)) if previous_template == tid else spec.default
                texts[spec.id] = self.ask(f"  {spec.label or spec.id}", default)
        cfg["texts"] = texts

        if tpl.guest_field.enabled:
            cfg["guest_name"] = self.yes_no(S["wiz_guest"], bool(cfg.get("guest_name")))
        else:
            self.say(S["wiz_guest_unsupported"])
            cfg["guest_name"] = False

        profiles = list_profiles()
        p_loaded = {p: load_profile(p) for p in profiles}
        p_labels = [f"{p_loaded[p].model} ({p_loaded[p].status})" for p in profiles]
        current = profiles.index(cfg["printer"]["profile"]) if cfg["printer"]["profile"] in profiles else 0
        pid = self.choose(S["wiz_profile"], profiles, p_labels, current)
        profile = p_loaded[pid]
        cfg["printer"]["profile"] = pid
        cfg["printer"]["density"] = profile.density.get("default", 3)

        driver = self.choose(S["wiz_driver"], list(DRIVERS), default=0)
        if driver != "mock":
            self.say(S["wiz_driver_stub"])
        cfg["printer"]["driver"] = driver

        sizes = [f"{a:g}x{b:g}" for a, b in (profile.label_sizes_mm or [[50, 80]])]
        while True:
            raw = self.ask(f"{S['wiz_label']} ({', '.join(sizes)})", sizes[0]).lower().replace(" ", "")
            m = re.fullmatch(r"(\d+(?:[.,]\d+)?)[x×*](\d+(?:[.,]\d+)?)", raw)
            if m:
                w, h = (float(v.replace(",", ".")) for v in m.groups())
                if 5 <= w <= 120 and 5 <= h <= 300:
                    cfg["label"] = {"width_mm": w, "height_mm": h}
                    break
            self.say(S["wiz_bad_label"])

        if profile.grayscale:
            cfg["paper"] = self.choose(S["wiz_paper"], ["photo", "regular"],
                                       default=0 if cfg.get("paper", "photo") == "photo" else 1)
        else:
            self.say(S["wiz_paper_forced"])
            cfg["paper"] = "regular"

        current_pin = C.admin_pin()
        while True:
            pin = self.ask(S["wiz_pin"], current_pin)
            if re.fullmatch(r"\d{4,8}", pin):
                break
            self.say(S["wiz_bad_pin"])

        C.save_config(cfg)
        C.write_env({"NIIMPARTY_ADMIN_PIN": pin})
        self.say(f"\n{S['wiz_saved']}\n")
        return cfg


def run_wizard() -> dict[str, Any]:
    return Wizard().run()
