# services/rundeck_executor.py
import os
from .executor_interface import ExecutorInterface
from .rundeck import build_job_yaml, import_job, run_job, get_execution_state, get_execution_output


class RundeckExecutor(ExecutorInterface):

    def run(self, ticket, plan, options, context):

    # 1️⃣ Collect commands from plan
        commands = []
        for step in plan["steps"]:
            commands.extend(step["commands"])

        runtime_environment = options.get("environment")
        runtime_version = options.get("version")

        final_commands = []

        for cmd in commands:
        # normalize single brace fallback
            cmd = cmd.replace("{environment}", "{{ environment }}")
            cmd = cmd.replace("{version}", "{{ version }}")

        # now render runtime values
            cmd = cmd.replace("{{ environment }}", runtime_environment)
            cmd = cmd.replace("{{ version }}", runtime_version)

            final_commands.append(cmd)

    # 2️⃣ Build YAML using final_commands
        yaml_payload = build_job_yaml(
        ticket,
        plan,
        commands=final_commands
    )

        result = import_job(yaml_payload)

        if not result.get("succeeded"):
           raise Exception("Rundeck job import failed")

        job_id = result["succeeded"][0]["id"]

        execution = run_job(job_id, options=options)

        return execution
    def get_status(self, execution_id):
        return get_execution_state(execution_id)

    def get_logs(self, execution_id):
        return get_execution_output(execution_id)
    
    

    def get_execution_url(self, execution_id):
        base = os.getenv("RUNDECK_BASE_URL")
        project = os.getenv("RUNDECK_PROJECT")
        return f"{base}/project/{project}/execution/show/{execution_id}"