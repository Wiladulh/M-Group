"""Shared pytest configuration.

Admin API tests must authenticate through the real WebUI login endpoint and
carry the resulting session cookie. No legacy admin-token compatibility shim
is installed here.
"""
