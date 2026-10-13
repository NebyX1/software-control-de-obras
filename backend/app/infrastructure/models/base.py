"""Tipos y utilidades comunes de los modelos."""
from sqlalchemy import text
from sqlalchemy.dialects.mysql import DATETIME
from app.extensions import db

Money = db.Numeric(18, 2)
Qty = db.Numeric(18, 4)
Rate = db.Numeric(8, 3)
Score = db.Numeric(30, 12)


def ts(nullable=False, default=True):
    """Marca de tiempo de servidor en UTC (el servidor de base de datos opera en +00:00)."""
    kwargs = {'server_default': text('CURRENT_TIMESTAMP(6)')} if default and not nullable else {}
    return db.Column(DATETIME(fsp=6), nullable=nullable, **kwargs)


def ts_null():
    return db.Column(DATETIME(fsp=6), nullable=True)


def fk(target, nullable=False, index=True, ondelete=None):
    return db.Column(db.Integer, db.ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)
