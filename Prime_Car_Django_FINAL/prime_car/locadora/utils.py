"""Funções utilitárias sem dependência dos modelos (evita importação circular)."""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value):
    """Arredonda para 2 casas decimais (centavos), meio para cima."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def format_brl(value):
    """Formata um valor como moeda brasileira: R$ 1.234,50 (negativos: -R$ 10,00)."""
    if value is None:
        return ""
    value = money(value)
    sign = "-" if value < 0 else ""
    integer, decimals = f"{abs(value):.2f}".split(".")
    integer = f"{int(integer):,}".replace(",", ".")
    return f"{sign}R$ {integer},{decimals}"


def format_percent(value):
    """10.00 -> '10'; 7.50 -> '7,5'."""
    text = f"{Decimal(value):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")
