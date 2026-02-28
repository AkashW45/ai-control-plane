import os
from services.rundeck import (
    build_job_yaml,
    import_job,
    run_job
)
from services.awx_executor import AWXExecutor


class Executor:

    def __init__(self, executor_type):
        self.executor_type = executor_type

        if executor_type == "awx":
            self.engine = AWXExecutor()

    def run(self, ticket, plan, options, context):

        if self.executor_type == "rundeck":

            yaml_payload = build_job_yaml(ticket, plan)
            result = import_job(yaml_payload)

            job_id = result["succeeded"][0]["id"]

            execution = run_job(job_id, options=options)
            return execution

        elif self.executor_type == "awx":

            return self.engine.run(ticket, plan, options, context)

        else:
            raise Exception("Unsupported executor")