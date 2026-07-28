"""Limitação de taxa (proteção contra força bruta no login)."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
