import os
from .executor_interface import ExecutorInterface
from .rundeck import build_job_yaml, import_job, run_job, get_execution_state, get_execution_output


class RundeckExecutor(ExecutorInterface):

    def run(self, ticket, plan, options, context):

        runtime_environment = options.get("environment")
        runtime_version     = options.get("version")

        # Collect all commands from plan steps and resolve variables
        # (preserving original executor contract — executor owns substitution)
        commands = []
        for step in plan["steps"]:
            for cmd in step["commands"]:
                cmd = cmd.replace("{environment}",   "{{ environment }}")
                cmd = cmd.replace("{version}",        "{{ version }}")
                cmd = cmd.replace("{{ environment }}", runtime_environment)
                cmd = cmd.replace("{{ version }}",     runtime_version)
                cmd = cmd.replace("${option.environment}", runtime_environment)
                cmd = cmd.replace("${option.version}",     runtime_version)
                commands.append(cmd)

        # Build YAML — executor passes resolved final_commands
        # build_job_yaml distributes them back per step for clean labelled output
        yaml_payload = build_job_yaml(ticket, plan, commands=commands)

        result = import_job(yaml_payload)

        if not result.get("succeeded"):
            raise Exception(f"Rundeck job import failed: {result}")

        job_id    = result["succeeded"][0]["id"]
        execution = run_job(job_id, options=options)

        return execution

    def get_status(self, execution_id):
        return get_execution_state(execution_id)

    def get_logs(self, execution_id):
        return get_execution_output(execution_id)

    def get_execution_url(self, execution_id):
        base    = os.getenv("RUNDECK_BASE_URL", "")
        project = os.getenv("RUNDECK_PROJECT", "")
        return f"{base}/project/{project}/execution/show/{execution_id}"