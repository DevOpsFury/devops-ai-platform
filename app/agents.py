import json

from app.config import settings
from app.llm import complete

AGENTS = {
    "triage": (
        "Jesteś agentem triage w zespole SRE. Oddziel fakty z wejścia od hipotez. "
        "Nie wymyślaj telemetrii ani wyników narzędzi."
    ),
    "observability": (
        "Jesteś analitykiem observability. Oceń dostarczone dowody i wskaż, "
        "jakich pomiarów brakuje do empirycznej weryfikacji diagnozy."
    ),
    "security": (
        "Jesteś recenzentem SecOps. Wskaż ryzyko rekomendacji, minimalne uprawnienia "
        "i czy wymagane jest zatwierdzenie przez człowieka. Nie proponuj wykonania zmian."
    ),
}

SUPERVISOR = (
    "Jesteś koordynatorem zespołu agentów AI DevOps. Przygotuj zwięzły raport po polsku "
    "z sekcjami: PROBLEM, DOWODY, HIPOTEZA (nie fakt), PEWNOŚĆ, BRAKUJĄCE DANE, "
    "REKOMENDOWANE NASTĘPNE KROKI, RYZYKO I ZATWIERDZENIE. Nie twierdź, że wykonano "
    "jakiekolwiek działania. Jeśli brakuje danych operacyjnych, powiedz to wprost."
)


def diagnose(title: str, description: str, environment: str, evidence: list[dict]) -> tuple[dict, str]:
    case = {
        "incident": {"title": title, "description": description, "environment": environment},
        "retrieved_runbooks": evidence,
        "limitation": (
            "System ma wyłącznie dokumenty z bazy wiedzy. Nie ma podłączonego monitoringu, "
            "repozytorium wdrożeń ani dostępu wykonawczego do infrastruktury."
        ),
    }
    case_text = json.dumps(case, ensure_ascii=False)
    reports = {
        name: complete(prompt, f"Przeanalizuj incydent i podaj zwięzły raport:\n{case_text}")
        for name, prompt in AGENTS.items()
    }
    final_report = complete(
        SUPERVISOR,
        "Zsyntetyzuj raporty specjalistów i dane incydentu. Nie dodawaj nowych faktów.\n"
        + json.dumps({"case": case, "agent_reports": reports}, ensure_ascii=False),
    )
    return reports, final_report


def provider_metadata() -> tuple[str, str]:
    return settings.llm_provider, settings.llm_model
