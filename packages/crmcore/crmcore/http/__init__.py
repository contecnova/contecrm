"""Capa HTTP: contratos, middleware y las garantías del Módulo 0.2."""

from crmcore.http.etag import comprobar_if_match, etag_de
from crmcore.http.pagination import Cursor, Pagina, ParametrosPagina

__all__ = ["Cursor", "Pagina", "ParametrosPagina", "comprobar_if_match", "etag_de"]
