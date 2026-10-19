# Superset runs from its own image: it declares Python 3.10-3.12, not the project's 3.14.
FROM apache/superset:6.1.0

USER root
RUN uv pip install --python /app/.venv/bin/python clickhouse-connect==1.9.0 psycopg2-binary==2.9.13
COPY superset_config.py /app/pythonpath/superset_config.py
COPY init/init.sh /app/init.sh
COPY init/provision_connection.py /app/provision_connection.py
COPY assets /app/assets
RUN chmod +x /app/init.sh
USER superset

CMD ["/app/init.sh"]
