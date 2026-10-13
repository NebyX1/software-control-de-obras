"""Esquemas estrictos de salida del modelo y utilidades de verificación de evidencia."""
import json
import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROMPT_VERSION = 'cc-ai-v1'
FIELD_KEYS = ('unit_price', 'tax_rate', 'quantity', 'currency', 'freight', 'delivery_days', 'warranty_months', 'delivery_terms', 'supplier_name', 'total')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ExtractedItem(Strict):
    key: Literal['unit_price', 'tax_rate', 'quantity', 'currency', 'freight', 'delivery_days', 'warranty_months', 'delivery_terms', 'supplier_name', 'total']
    value: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=1, le=5000)
    quote: str = Field(min_length=3, max_length=600)


class ExtractionOut(Strict):
    fields: list[ExtractedItem] = Field(max_length=20)
    issues: list[str] = Field(max_length=20)


def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', s).strip()


def parse_json_object(raw):
    """Extrae el primer objeto JSON de una respuesta. Levanta ValueError si no hay uno válido."""
    start, end = raw.find('{'), raw.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('sin objeto JSON')
    return json.loads(raw[start:end + 1])


def validate_extraction(raw):
    """Validación estricta; nunca 'arregla' valores ni inventa evidencia."""
    try:
        return ExtractionOut.model_validate(parse_json_object(raw)), None
    except (ValueError, ValidationError) as exc:
        return None, str(exc)[:300]


def quote_in_page(quote, page_text):
    return norm(quote) in norm(page_text)


def value_in_quote(value, quote):
    digits = lambda s: re.sub(r'[^\d]', '', s)
    v = digits(value)
    if v:
        return v in digits(quote)
    return norm(value) in norm(quote)


NUM = re.compile(r'\d[\d.,]*')


def numbers_in(text):
    out = set()
    for m in NUM.findall(text):
        out.add(re.sub(r'[.,]', '', m).lstrip('0') or '0')
    return out
