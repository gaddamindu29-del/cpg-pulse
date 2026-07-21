FROM apache/airflow:2.9.2-python3.11

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recursive build-essential curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Airflow's own pinned constraints file keeps this install conflict-free
# against the exact Airflow version above.
ARG AIRFLOW_VERSION=2.9.2
ARG PYTHON_VERSION=3.11
ARG CONSTRAINT_URL=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt

COPY requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir -r /requirements-airflow.txt --constraint "${CONSTRAINT_URL}"

# DAGs import ingestion/spark/scripts modules directly (see airflow/dags/*.py),
# so the repo subset mounted by docker-compose.yml needs to be importable.
ENV PYTHONPATH=/opt/airflow/repo
