"""Shared bounds and conservative screening for the Business bot."""
import re

MAX_BATCH_MESSAGES = 12
MAX_BATCH_CHARS = 4000
RISK = re.compile(r'(?iu)(парол|password|passcode|секрет|secret|токен|token|код.{0,16}(вход|подтверж|авториз)|\b(otp|pin|cvv|cvc|2fa)\b|\b\d{6,}\b|деньг|рубл|кредит|займ|оплат|payment|money|банк|bank|договор|contract|обязую|гарантир|guarantee|согласие|consent|диагноз|diagnos|лекарств|уволь|женись|marry|развод|\bsk-[A-Za-z0-9_-]{12,}|\b(?:verification|login|security)\s+code\b|system prompt|ignore.{0,20}instruct)')


def is_sensitive(text):
    normalized=' '.join(text.split())
    return bool(RISK.search(normalized) or (re.fullmatch(r'[0-9 -]+',normalized) and len(re.sub(r'[^0-9]','',normalized))>=4))
