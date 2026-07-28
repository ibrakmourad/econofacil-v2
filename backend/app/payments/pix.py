"""Geração do BR Code Pix ("copia e cola") conforme o padrão EMV®/BCB.

O payload é uma sequência de campos no formato TLV: ``ID(2) + tamanho(2) +
valor``. O campo 63 (CRC) é calculado com CRC16-CCITT (polinômio 0x1021,
inicial 0xFFFF) sobre todo o payload já incluindo "6304". Isto produz um código
válido e verificável — o mesmo que um app bancário leria — ainda que aqui
nenhum dinheiro real seja movimentado.
"""
from __future__ import annotations

import re
import unicodedata

import qrcode


def _tlv(field_id: str, value: str) -> str:
    return f"{field_id}{len(value):02d}{value}"


def _ascii_upper(text: str, max_len: int) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^A-Za-z0-9 ]", "", norm).upper().strip()
    return norm[:max_len] or "NA"


def sanitize_txid(txid: str, max_len: int = 25) -> str:
    clean = re.sub(r"[^A-Za-z0-9]", "", txid)
    return clean[:max_len] or "TX"


def crc16(payload: str) -> str:
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return format(crc, "04X")


def build_pix_payload(
    *, key: str, merchant_name: str, merchant_city: str, amount: float, txid: str
) -> str:
    """Monta o BR Code Pix dinâmico (com valor) e anexa o CRC16."""
    merchant_account = _tlv("00", "br.gov.bcb.pix") + _tlv("01", key)
    additional = _tlv("05", sanitize_txid(txid))

    payload = (
        _tlv("00", "01")                                  # Payload Format Indicator
        + _tlv("26", merchant_account)                    # Merchant Account Information
        + _tlv("52", "0000")                              # Merchant Category Code
        + _tlv("53", "986")                               # Moeda (BRL)
        + _tlv("54", f"{amount:.2f}")                     # Valor
        + _tlv("58", "BR")                                # País
        + _tlv("59", _ascii_upper(merchant_name, 25))     # Nome do recebedor
        + _tlv("60", _ascii_upper(merchant_city, 15))     # Cidade
        + _tlv("62", additional)                          # Dados adicionais (txid)
        + "6304"                                          # prefixo do CRC
    )
    return payload + crc16(payload)


def verify_payload(payload: str) -> bool:
    """Confere o CRC de um BR Code (útil em testes)."""
    if len(payload) < 4:
        return False
    body, given = payload[:-4], payload[-4:]
    return crc16(body) == given.upper()


def build_qr_svg(data: str, box: int = 4, border: int = 4) -> str:
    qr = qrcode.QRCode(border=border, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    dim = len(matrix) * box
    rects = "".join(
        f'<rect x="{c * box}" y="{r * box}" width="{box}" height="{box}"/>'
        for r, row in enumerate(matrix)
        for c, val in enumerate(row)
        if val
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" '
        f'viewBox="0 0 {dim} {dim}"><rect width="{dim}" height="{dim}" fill="#fff"/>'
        f'<g fill="#000">{rects}</g></svg>'
    )
