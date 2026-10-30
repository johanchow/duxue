"""Versioned, code-validated Agent workflow definitions."""

def load_catalog():
    from app.agent_specs.catalog import load_catalog as load
    return load()


__all__ = ["load_catalog"]
