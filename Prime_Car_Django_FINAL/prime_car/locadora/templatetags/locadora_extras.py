from django import template

from locadora.utils import format_brl, format_percent

register = template.Library()


@register.filter
def brl(value):
    """Formata valores monetários em reais."""
    return format_brl(value)


@register.filter
def percent(value):
    return format_percent(value)
