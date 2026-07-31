"""Public intake parsing for the Hermes Research plugin."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

ALIASES = {
    "topic": {"tema"},
    "research_question": {"pregunta de investigacion", "pregunta de investigacion (opcional)"},
    "year_or_years": {"ano o anos", "año o años"},
    "from_date": {"fecha inicial", "fecha inicial (opcional)"},
    "to_date": {"fecha final", "fecha final (opcional)"},
    "inclusion_criteria": {"criterios de inclusion", "criterios de inclusión"},
    "exclusion_criteria": {"criterios de exclusion", "criterios de exclusión"},
    "author_filters": {"autores"},
    "manuscript_authors": {
        "autoria del manuscrito",
        "autoría del manuscrito",
        "autoria del manuscrito (opcional)",
        "autoría del manuscrito (opcional)",
        "autor del manuscrito",
        "autor del manuscrito (opcional)",
        "autores del manuscrito",
        "autores del manuscrito (opcional)",
    },
    "manuscript_email": {
        "correo de contacto",
        "correo de contacto (opcional)",
        "email de contacto",
        "email de contacto (opcional)",
        "correo",
        "email",
    },
    "manuscript_date": {
        "fecha del manuscrito",
        "fecha del manuscrito (opcional)",
        "fecha de version",
        "fecha de versión",
        "fecha de version (opcional)",
        "fecha de versión (opcional)",
        "fecha de publicacion",
        "fecha de publicación",
        "fecha de publicacion (opcional)",
        "fecha de publicación (opcional)",
    },
    "autonomous_mode": {
        "modo autonomo",
        "modo autónomo",
        "modo autonomo (opcional; por defecto: si)",
        "modo autónomo (opcional; por defecto: sí)",
    },
    "review_mode": {
        "modo metodologico",
        "modo metodológico",
        "modo metodologico (opcional)",
        "modo metodológico (opcional)",
        "campo",
        "campo metodologico",
        "campo metodológico",
    },
    "final_n": {
        "limite final n",
        "límite final n",
        "limite final n ultraquality",
        "límite final n ultraquality",
        "limite final n (opcional; por defecto: 37)",
        "límite final n (opcional; por defecto: 37)",
    },
    "representativeness": {
        "criterio de representatividad ultraquality",
        "representatividad ultraquality",
    },
    "target_outlet": {
        "revista o medio objetivo",
        "revista o medio objetivo (opcional)",
    },
    "target_length": {"longitud objetivo del manuscrito", "longitud objetivo del manuscrito (opcional)"},
}

WIZARD_STEPS = [
    {
        "field": "topic",
        "label": "tema",
        "required": True,
        "prompt": (
            "**1/12 — Tema**\n"
            "¿Sobre qué tema quieres la revisión?\n\n"
            "Ejemplo: `agentes de IA en empresas 2025-2026`"
        ),
    },
    {
        "field": "year_or_years",
        "label": "años",
        "required": True,
        "prompt": (
            "**2/12 — Ventana temporal**\n"
            "¿Qué años debe cubrir?\n\n"
            "Ejemplo: `2025-2026`"
        ),
    },
    {
        "field": "inclusion_criteria",
        "label": "criterios de inclusión",
        "required": True,
        "prompt": (
            "**3/12 — Criterios de inclusión**\n"
            "¿Qué estudios deben entrar sí o sí?\n\n"
            "Ejemplo: `estudios con texto completo, metodología explícita y resultados verificables`"
        ),
    },
    {
        "field": "exclusion_criteria",
        "label": "criterios de exclusión",
        "required": True,
        "prompt": (
            "**4/12 — Criterios de exclusión**\n"
            "¿Qué debe quedar fuera?\n\n"
            "Ejemplo: `opiniones, notas breves, entradas sin DOI ni PDF legible`"
        ),
    },
    {
        "field": "research_question",
        "label": "pregunta de investigación",
        "required": False,
        "default": "",
        "prompt": (
            "**5/12 — Pregunta de investigación**\n"
            "Si ya tienes una pregunta, escríbela. Si prefieres que Hermes la formule desde el tema y los criterios, responde `saltar`."
        ),
    },
    {
        "field": "review_mode",
        "label": "modo metodológico",
        "required": False,
        "default": "",
        "prompt": (
            "**6/12 — Campo metodológico**\n"
            "Si sabes el campo, escribe uno de estos: `biomédico`, `técnico`, `ciencias sociales`, `educación`, `management` o `mixto`.\n\n"
            "Si no lo tienes claro, responde `saltar`: Hermes lo ubicará y dejará la justificación en el protocolo."
        ),
    },
    {
        "field": "final_n",
        "label": "N final",
        "required": False,
        "default": "37",
        "prompt": (
            "**7/12 — N final objetivo**\n"
            "¿Cuántos estudios finales quieres como objetivo?\n\n"
            "Responde un número, por ejemplo `33`, un rango como `11-75`, o `saltar` para usar `37`."
        ),
    },
    {
        "field": "target_outlet",
        "label": "revista o medio",
        "required": False,
        "default": "generic-common-core",
        "prompt": (
            "**8/12 — Revista o medio objetivo**\n"
            "Si hay una revista, congreso o medio concreto, escríbelo. Si no, responde `saltar` y Hermes usará `generic-common-core`."
        ),
    },
    {
        "field": "manuscript_authors",
        "label": "autoría del manuscrito",
        "required": False,
        "default": "",
        "prompt": (
            "**9/12 — Autoría del manuscrito**\n"
            "Si quieres que el PDF muestre autoría, escribe el nombre tal como debe aparecer. Si no, responde `saltar`."
        ),
    },
    {
        "field": "manuscript_email",
        "label": "correo de contacto",
        "required": False,
        "default": "",
        "prompt": (
            "**10/12 — Correo de contacto**\n"
            "Si quieres mostrar un correo de contacto en el PDF, escríbelo. Si no, responde `saltar`."
        ),
    },
    {
        "field": "manuscript_date",
        "label": "fecha del manuscrito",
        "required": False,
        "default": "",
        "prompt": (
            "**11/12 — Fecha del manuscrito**\n"
            "Si quieres fijar una fecha visible en el PDF, escríbela. Si no, responde `saltar`."
        ),
    },
    {
        "field": "autonomous_mode",
        "label": "modo autónomo",
        "required": False,
        "default": "sí",
        "prompt": (
            "**12/12 — Modo de ejecución**\n"
            "¿Quieres que Hermes siga solo hasta donde pueda después de crear el protocolo?\n\n"
            "Responde `sí` para ciclo autónomo o `no` para dejarlo creado y pausado."
        ),
    },
]


def intake_template() -> str:
    """Return the public intake block shown to gateway users."""
    return (
        "Tema:\n"
        "Año o años:\n"
        "Criterios de inclusión:\n"
        "Criterios de exclusión:\n"
        "Pregunta de investigación (opcional):\n"
        "Autoría del manuscrito (opcional):\n"
        "Correo de contacto (opcional):\n"
        "Fecha del manuscrito (opcional):\n"
        "Modo autónomo:\n"
        "Modo metodológico (opcional):\n"
        "Límite final N:\n"
        "Revista o medio objetivo (opcional):\n"
    )


def looks_like_intake_block(text: str) -> bool:
    """Return True when the text resembles the public intake format."""
    normalized = (text or "").lower()
    if "tema:" not in normalized:
        return False
    score = 0
    for marker in (
        "año o años:",
        "ano o anos:",
        "criterios de inclusión:",
        "criterios de inclusion:",
        "criterios de exclusión:",
        "criterios de exclusion:",
        "pregunta de investigación:",
        "pregunta de investigacion:",
    ):
        if marker in normalized:
            score += 1
    return score >= 2


def _normalize_label(text: str) -> str:
    value = (text or "").strip().lstrip("-").strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def normalize_value(text: str) -> str:
    """Normalize a short user reply for tolerant command matching."""
    return _normalize_label(text)


def wizard_state_path():
    """Return the shared public Telegram wizard-state path."""
    from . import runtime

    return runtime.hermes_home() / "public-prisma-wizard-state.json"


def load_wizard_states() -> dict:
    """Load all in-progress public Telegram intake conversations."""
    path = wizard_state_path()
    with _wizard_lock(path, exclusive=False):
        return _load_wizard_states_unlocked(path)


def _load_wizard_states_unlocked(path) -> dict:
    """Read wizard state while the caller holds the appropriate lock."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_wizard_states_unlocked(path, states: dict) -> None:
    """Atomically save wizard state while the caller holds an exclusive lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(json.dumps(states, ensure_ascii=False, indent=2) + "\n")
        # Preserve the last complete state if the process stops mid-write.
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = type(path)(handle.name)
    temp_path.chmod(0o600)
    temp_path.replace(path)


@contextmanager
def _wizard_lock(path, *, exclusive: bool):
    """Serialize wizard state updates across concurrent messages."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def wizard_active(binding_key: str) -> bool:
    """Return True when this chat has an in-progress intake wizard."""
    return bool(binding_key and load_wizard_states().get(binding_key))


def get_wizard_state(binding_key: str) -> dict | None:
    """Return the wizard state for one chat binding."""
    if not binding_key:
        return None
    state = load_wizard_states().get(binding_key)
    return state if isinstance(state, dict) else None


def save_wizard_state(binding_key: str, state: dict) -> None:
    """Persist one chat's wizard state."""
    if not binding_key:
        return
    path = wizard_state_path()
    with _wizard_lock(path, exclusive=True):
        states = _load_wizard_states_unlocked(path)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        states[binding_key] = state
        _save_wizard_states_unlocked(path, states)


def clear_wizard_state(binding_key: str) -> None:
    """Delete one chat's wizard state."""
    if not binding_key:
        return
    path = wizard_state_path()
    with _wizard_lock(path, exclusive=True):
        states = _load_wizard_states_unlocked(path)
        if binding_key in states:
            states.pop(binding_key, None)
            _save_wizard_states_unlocked(path, states)


def wizard_question(step_index: int) -> str:
    """Return the prompt for one wizard step."""
    step = WIZARD_STEPS[min(step_index, len(WIZARD_STEPS) - 1)]
    return f"{step['prompt']}\n\nPuedes escribir `cancelar` en cualquier momento."


def payload_to_intake_block(payload: dict[str, str]) -> str:
    """Render a wizard payload back to the legacy intake block format."""
    return (
        f"Tema: {payload.get('topic', '').strip()}\n"
        f"Año o años: {payload.get('year_or_years', '').strip()}\n"
        f"Criterios de inclusión: {payload.get('inclusion_criteria', '').strip()}\n"
        f"Criterios de exclusión: {payload.get('exclusion_criteria', '').strip()}\n"
        f"Pregunta de investigación (opcional): {payload.get('research_question', '').strip()}\n"
        f"Autoría del manuscrito (opcional): {payload.get('manuscript_authors', '').strip()}\n"
        f"Correo de contacto (opcional): {payload.get('manuscript_email', '').strip()}\n"
        f"Fecha del manuscrito (opcional): {payload.get('manuscript_date', '').strip()}\n"
        f"Modo autónomo: {payload.get('autonomous_mode', 'sí').strip()}\n"
        f"Modo metodológico (opcional): {payload.get('review_mode', '').strip()}\n"
        f"Límite final N: {payload.get('final_n', '37').strip()}\n"
        f"Revista o medio objetivo (opcional): {payload.get('target_outlet', 'generic-common-core').strip()}\n"
    )


def wizard_summary(payload: dict[str, str]) -> str:
    """Summarize a completed wizard before creating review artifacts."""
    return "\n".join(
        [
            "**Resumen antes de crear la revisión**",
            f"- Tema: {payload.get('topic', '').strip()}",
            f"- Años: {payload.get('year_or_years', '').strip()}",
            f"- Inclusión: {payload.get('inclusion_criteria', '').strip()}",
            f"- Exclusión: {payload.get('exclusion_criteria', '').strip()}",
            f"- Pregunta: {payload.get('research_question', '').strip() or 'Hermes la formulará desde el protocolo'}",
            f"- N final objetivo: {payload.get('final_n', '37').strip()}",
            f"- Revista o medio: {payload.get('target_outlet', 'generic-common-core').strip()}",
            f"- Autoría manuscrito: {payload.get('manuscript_authors', '').strip() or 'sin autoría declarada'}",
            f"- Correo contacto: {payload.get('manuscript_email', '').strip() or 'no declarado'}",
            f"- Fecha manuscrito: {payload.get('manuscript_date', '').strip() or 'no declarada'}",
            f"- Modo metodológico: {payload.get('review_mode', '').strip() or 'Hermes lo inferirá y lo auditará'}",
            f"- Modo autónomo: {payload.get('autonomous_mode', 'sí').strip()}",
            "",
            "Responde `crear` para generar los artefactos iniciales o `cancelar` para parar.",
        ]
    )


def validate_wizard_value(field: str, value: str) -> tuple[str | None, str | None]:
    """Validate one human reply and return ``(clean_value, error)``."""
    clean = (value or "").strip()
    normalized = normalize_value(clean)
    if field == "final_n":
        if normalized in {"saltar", "skip", "omitir", ""}:
            return "37", None
        if clean.isdigit() and int(clean) > 0:
            return clean, None
        if "-" in clean:
            parts = [part.strip() for part in clean.split("-", 1)]
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                low, high = sorted(int(part) for part in parts)
                if low > 0 and high > 0:
                    return f"{low}-{high}", None
        return None, "Necesito un número entero positivo o un rango, por ejemplo `33`, `11-75` o `saltar`."
    if field == "autonomous_mode":
        if normalized in {"saltar", "skip", "omitir", ""}:
            return "sí", None
        if normalized in {"si", "sí", "s", "yes", "y", "true", "1", "autonomo", "autónomo"}:
            return "sí", None
        if normalized in {"no", "n", "false", "0", "manual", "pausa", "pausado"}:
            return "no", None
        return None, "Responde `sí` para continuar automáticamente o `no` para dejar la revisión creada y pausada."
    if field == "review_mode":
        if normalized in {"saltar", "skip", "omitir", ""}:
            return "", None
        mapping = {
            "biomedico": "biomédico",
            "biomedica": "biomédico",
            "biomedical": "biomédico",
            "salud": "biomédico",
            "tecnico": "técnico",
            "tecnica": "técnico",
            "technical": "técnico",
            "ingenieria": "técnico",
            "ciencias sociales": "ciencias sociales",
            "ciencia social": "ciencias sociales",
            "social": "ciencias sociales",
            "social sciences": "ciencias sociales",
            "educacion": "educación",
            "education": "educación",
            "educativo": "educación",
            "management": "management",
            "direccion": "management",
            "estrategia": "management",
            "empresa": "management",
            "negocio": "management",
            "mixto": "mixto",
            "mixed": "mixto",
        }
        if normalized in mapping:
            return mapping[normalized], None
        return None, "Responde con `biomédico`, `técnico`, `ciencias sociales`, `educación`, `management`, `mixto` o `saltar`."
    if not clean:
        return None, "Necesito una respuesta con algo de contenido para este campo."
    return clean, None


def parse_intake_block(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse the user-facing intake block into the normalized bootstrap payload."""
    payload: dict[str, str] = {}
    normalized_text = (text or "").replace(" | ", "\n")
    for raw_line in normalized_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        raw_label, raw_value = line.split(":", 1)
        label = _normalize_label(raw_label)
        value = raw_value.strip()
        if label.endswith("(opcional; por defecto") and "):" in value:
            _, _, actual_value = value.partition("):")
            label = label.replace(" (opcional; por defecto", "").strip()
            value = actual_value.strip()
        if not value:
            continue
        for field, aliases in ALIASES.items():
            if label in aliases:
                payload[field] = value
                break

    payload.setdefault("research_question", "")
    payload.setdefault("from_date", "")
    payload.setdefault("to_date", "")
    payload.setdefault("author_filters", "")
    payload.setdefault("manuscript_authors", "")
    payload.setdefault("manuscript_email", "")
    payload.setdefault("manuscript_date", "")
    payload.setdefault("autonomous_mode", "sí")
    payload.setdefault("review_mode", "")
    payload.setdefault("final_n", "37")
    payload.setdefault("representativeness", "")
    payload.setdefault("target_outlet", "generic-common-core")
    payload.setdefault("target_length", "")

    missing = []
    required = (
        ("topic", "Tema"),
        ("year_or_years", "Año o años"),
        ("inclusion_criteria", "Criterios de inclusión"),
        ("exclusion_criteria", "Criterios de exclusión"),
    )
    for field, label in required:
        if not (payload.get(field) or "").strip():
            missing.append(label)

    return payload, missing
