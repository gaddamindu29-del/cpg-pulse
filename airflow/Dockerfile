FROM apache/airflow:2.9.2-python3.11

USER root
# default-jdk-headless: PySpark needs a real JVM to execute jobs (not just to
# import the pyspark package). This was missing entirely from earlier drafts
# of this Dockerfile -- the "run Spark jobs inside this container" plan was
# documented (docs/architecture.md, docs/runbook.md) but never actually
# implemented, since Docker wasn't available to build and catch this until
# now. `JAVA_HOME` is exported below because PySpark's own auto-detection
# doesn't reliably find Debian's JDK install location.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl default-jdk-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

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
