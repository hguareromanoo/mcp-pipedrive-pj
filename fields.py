# ─────────────────────────────────────────────
# fields.py
# Pipedrive field keys and option maps
# ─────────────────────────────────────────────


# ── Custom Field Keys (hash keys) ─────────────────────────────────────────────

DRIVE_FIELD        = "ede9bf995bb2d7e50ea8ffbfd24cb56e72232ff0"  # varchar  — Link Drive das Gravações
CANAL_FIELD        = "97d0502cc2b489986844a93b374656e5acf179e1"  # enum     — Canal de Entrada
PORTFOLIO_FIELD    = "e4339ab04542dcd1e1215e4bc17ee2bcf45a9652"  # set      — Portfólio (multi-select)
SETOR_FIELD        = "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f"  # enum     — Setor da Empresa
FUNCIONARIOS_FIELD = "0b2be49fb7615b170878d944a7cb05f6ec8f9e27"  # enum     — Número de Funcionários


# ── Native Field Keys ─────────────────────────────────────────────────────────
# These use Pipedrive's built-in keys (not hashes).

PIPELINE_FIELD    = "pipeline"     # double          — Funil. Resolved via GET /pipelines
STAGE_FIELD       = "stage_id"     # stage           — Etapa. Resolved via GET /stages/{id}
LOST_REASON_FIELD = "lost_reason"  # varchar_options — Motivo da Perda
LABEL_FIELD       = "label"        # set             — Etiqueta (núcleo responsável)

# Note: pipeline and stage_id are resolved dynamically at runtime:
#   stage name    → GET /stages/{stage_id}       → stage["name"]
#   pipeline name → GET /pipelines/{pipeline_id} → pipeline["name"]


# ── Option Maps ───────────────────────────────────────────────────────────────
# Pipedrive returns numeric IDs for enum/set fields.
# These maps resolve IDs → human-readable labels.

CANAL_OPTIONS: dict[int, str] = {
    27: "Inbound",
    28: "Outbound",
    29: "Fidelização",
    30: "Indicação",
}

SETOR_OPTIONS: dict[int, str] = {
    244: "Não possui setor - Pessoa Física",
    156: "Computer Software & Internet",
    157: "Consumer Goods & Services",
    158: "Education",
    159: "Energy & Environment",
    160: "Entertainment",
    161: "Financial Services",
    162: "Food & Beverages",
    163: "Health & Fitness",
    164: "Human Resources",
    165: "Industrial",
    166: "Insurance",
    167: "Information Technology & Services",
    168: "Logistics & Supply Chain",
    169: "Marketing",
    170: "Outsourcing",
    171: "Real Estate",
    172: "Retail",
    173: "Telecommunications",
    174: "Agronegócio",
    176: "Veterinary",
    177: "Chemicals",
    178: "Architecture and Planning",
    179: "Airlines and Aviation",
    180: "Hospitality",
    181: "Construction",
    182: "Security",
    196: "Pharmaceutical Manufacturing",
    198: "Engineering Services",
    199: "Advertising Services",
    313: "Business Consulting and Services",
}

FUNCIONARIOS_OPTIONS: dict[int, str] = {
    245: "Não possui - Pessoa Física",
    183: "1-10",
    184: "11-50",
    185: "51-200",
    186: "201-500",
    187: "501-1,000",
    188: "1,001-5,000",
    189: "5,001-10,000",
    190: "10,001+",
}

# Portfólio is a `set` field — API returns comma-separated IDs e.g. "219,312"
# Labels are also injected into AssemblyAI word_boost for better transcription accuracy.
PORTFOLIO_OPTIONS: dict[int, str] = {
    # NDados
    460: "Portfólio não definido",
    219: "NDados - Extração",
    220: "NDados - Integração",
    206: "NDados - Visualização",
    218: "NDados - Análise Exploratória",
    222: "NDados - Previsão",
    401: "NDados - Automação",
    312: "NDados - IA Generativa",
    402: "NDados - IA de Voz",
    221: "NDados - Mapeamento",
    403: "NDados - IA de Imagem",
    207: "NDados - DSaaS",
    # NCiv
    223: "NCiv - Arquitetônico",
    225: "NCiv - Completo",
    226: "NCiv - DI",
    227: "NCiv - Elétrico",
    228: "NCiv - Estrutural",
    229: "NCiv - HE",
    230: "NCiv - HEE",
    231: "NCiv - Hidráulico",
    232: "NCiv - RE",
    399: "NCiv - Compatibilização",
    400: "NCiv - GO",
    # NCon
    215: "NCon - Gestão de Processos",
    217: "NCon - Modelagem e Projeção de Negócios",
    216: "NCon - Pesquisa de Mercado",
    # NTec
    208: "NTec - App",
    234: "NTec - Concepção",
    210: "NTec - Site",
    # WI
    211: "WI - Estande",
    213: "WI - Conexão",
    212: "WI - Palestra",
    214: "WI - Seleção WI",
    462: "WI - Inovacamp",
    # NI
    411: "NI - MAISA",
    412: "NI - Poli Bridge",
    536: "NI - Plum",
}

# Motivo da Perda — mandatory when status = lost
LOST_REASON_OPTIONS: dict[int, str] = {
    15:  "Budget",
    16:  "Autoridade",
    19:  "Demanda Desalinhada",
    20:  "Timing",
    153: "Inviabilidade Operacional para Executar",
    25:  "Comportamento Inadequado do Cliente",
    24:  "Vitória da Concorrência",
    22:  "Falha no Contato",
    154: "Sem Demanda",
    60:  "[SECRETÁRIA] Não deu continuidade",
    61:  "[SECRETÁRIA] Não atendemos a demanda",
    327: "[Outbound] Não se Interessou",
    328: "[Outbound] Timing",
    325: "[Outbound] Contato Encaminhado",
    326: "[Outbound] Não Respondeu",
}

# Etiqueta — identifies which núcleo owns the deal
LABEL_OPTIONS: dict[int, str] = {
    31:  "NCiv",
    33:  "NCon",
    32:  "NDados",
    286: "NI",
    34:  "NTec",
    152: "WI",
}


# ── Resolver Helpers ──────────────────────────────────────────────────────────

def resolve_enum(option_map: dict[int, str], raw_value) -> str:
    """Resolve a single enum ID (int or str) to its label."""
    if raw_value is None:
        return "[Não definido]"
    try:
        return option_map.get(int(raw_value), f"[ID desconhecido: {raw_value}]")
    except (ValueError, TypeError):
        return str(raw_value)


def resolve_set(option_map: dict[int, str], raw_value) -> list[str]:
    """
    Resolve a set field (comma-separated IDs) to a list of labels.
    e.g. "219,312" → ["NDados - Extração", "NDados - IA Generativa"]
    """
    if not raw_value:
        return []
    ids = str(raw_value).split(",")
    return [option_map.get(int(i.strip()), f"[ID: {i.strip()}]") for i in ids if i.strip()]
