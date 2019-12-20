""" This file contains common operators/functions to be used across multiple DAGs """
import json
import os
import urllib.parse
from datetime import date, timedelta
from typing import List

from airflow.contrib.kubernetes.pod import Resources

DATA_IMAGE = "registry.gitlab.com/gitlab-data/data-image/data-image:latest"
DBT_IMAGE = "registry.gitlab.com/gitlab-data/data-image/dbt-image:latest"

mm_webhook_url = os.getenv('MATTERMOST_WEBHOOK_URL')


def mm_failed_task(context):
    """
    Function to be used as a callable for on_failure_callback.
    Send a Mattermost alert.
    """
    if mm_webhook_url == None:
        return

    # Set all of the contextual vars
    base_url = "http://localhost:8080"
    execution_date = context["ts"]
    dag_context = context["dag"]
    dag_name = dag_context.dag_id
    dag_id = context["dag"].dag_id
    task_name = context["task"].task_id
    task_id = context["task_instance"].task_id
    execution_date_pretty = context["execution_date"].strftime(
        "%a, %b %d, %Y at %-I:%M %p UTC"
    )

    # Generate the link to the logs
    log_params = urllib.parse.urlencode(
        {"dag_id": dag_id, "task_id": task_id, "execution_date": execution_date}
    )
    log_link = f"{base_url}/log?{log_params}"
    log_link_markdown = f"[View Logs]({log_link})"

    body = f"""| DAG | Task | Logs | Timestamp |
        |-----|------|------|-----------|
        |{dag_name}|{task_name}|{log_link_markdown}|{execution_date_pretty}|
    """

    payload = {
        'username': 'Airflow',
        'text': body
    }

    os.system(f"""curl -i -X POST {mm_webhook_url} -H 'Content-Type: application/json' \
        --data-binary @- <<'EOF'
            {json.dumps(payload)}
        EOF
    """)



def split_date_parts(day: date, partition: str) -> List[dict]:

    if partition == "month":
        split_dict = {
            "year": day.strftime("%Y"),
            "month": day.strftime("%m"),
            "part": day.strftime("%Y_%m"),
        }

    return split_dict


def partitions(from_date: date, to_date: date, partition: str) -> List[dict]:
    """
    A list of partitions to build.
    """

    delta = to_date - from_date
    all_parts = [
        split_date_parts((from_date + timedelta(days=i)), partition)
        for i in range(delta.days + 1)
    ]

    seen = set()
    parts = []
    # loops through every day and pulls out unique set of date parts
    for p in all_parts:
        if p["part"] not in seen:
            seen.add(p["part"])
            parts.append({k: v for k, v in p.items()})
    return parts

# Set the resources for the task pods
pod_resources = Resources(request_memory="500Mi", request_cpu="500m")

# Default settings for all DAGs
pod_defaults = dict(
    get_logs=True,
    image_pull_policy="Always",
    in_cluster=True,
    is_delete_operator_pod=True,
    namespace=os.environ["NAMESPACE"],
#    resources=pod_resources,
    cmds=["/bin/bash", "-c"],
)

# Default environment variables for worker pods
env = os.environ.copy()
pod_env_vars = {
    "CI_PROJECT_DIR": "/analytics",
    "EXECUTION_DATE": "{{ next_execution_date }}",
    "SNOWFLAKE_LOAD_DATABASE": "DWH",
    "SNOWFLAKE_TRANSFORM_DATABASE": "ANALYTICS"
}

# Warehouse variable declaration
xs_warehouse = f"'{{warehouse_name: transforming_xs}}'"

clone_repo_cmd = f"git clone -b master --single-branch --depth 1 https://github.com/adovenmuehle/dbt"

clone_and_setup_extraction_cmd = f"""
    {clone_repo_cmd} &&
    export PYTHONPATH="$CI_PROJECT_DIR/orchestration/:$PYTHONPATH" &&
    cd analytics/extract/"""

clone_and_setup_dbt_cmd = f"""
    {clone_repo_cmd} &&
    cd dbt/transform/snowflake-dbt/"""

dbt_install_deps_cmd = f"""
    {clone_and_setup_dbt_cmd} &&
    dbt deps --profiles-dir profile"""

dbt_install_deps_and_seed_cmd = f"""
    {dbt_install_deps_cmd} &&
    dbt seed --profiles-dir profile --target prod --vars {xs_warehouse}"""
