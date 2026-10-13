"""Espera acotada a la base configurada; nunca crea ni reinicia un esquema."""
import os
import time
from sqlalchemy import create_engine, text

engine = create_engine(os.environ['DATABASE_URI'], pool_pre_ping=True, connect_args={'connect_timeout': 2})
for attempt in range(60):
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        engine.dispose()
        break
    except Exception:
        if attempt == 59:
            raise SystemExit('La base de datos no respondió dentro del tiempo de espera.')
        time.sleep(2)
