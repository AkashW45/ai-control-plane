import requests
import json
import os


class AWXExecutor:

    def __init__(self):
        self.base_url = os.getenv("AWX_URL", "http://localhost:8090")
        self.token = os.getenv("AWX_API_TOKEN")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        self.template_id = os.getenv("AWX_TEMPLATE_ID", "7")


    # --------------------------
    # 1️⃣ Run Job
    # --------------------------
    def run(self, ticket, plan, options, context):

        runtime_environment = options.get("environment")
        runtime_version = options.get("version")

        commands = []

        for step in plan["steps"]:
            for cmd in step["commands"]:

            # normalize single brace fallback
                cmd = cmd.replace("{environment}", "{{ environment }}")
                cmd = cmd.replace("{version}", "{{ version }}")

            # render runtime values
                cmd = cmd.replace("{{ environment }}", runtime_environment)
                cmd = cmd.replace("{{ version }}", runtime_version)

                commands.append(cmd)

        payload = {
        "extra_vars": {
            "environment": runtime_environment,
            "version": runtime_version,
            "commands": commands
        }
    }

        response = requests.post(
         f"{self.base_url}/api/v2/job_templates/{self.template_id}/launch/",
        headers=self.headers,
        data=json.dumps(payload),
        verify=False
    )

        response.raise_for_status()

        return response.json()


    # --------------------------
    # 2️⃣ Get Job Status
    # --------------------------
    def get_status(self, job_id):

        response = requests.get(
            f"{self.base_url}/api/v2/jobs/{job_id}/",
            headers=self.headers,
            verify=False
        )

        response.raise_for_status()

        return response.json()


    # --------------------------
    # 3️⃣ Get Logs
    # --------------------------
    def get_logs(self, job_id):

        response = requests.get(
            f"{self.base_url}/api/v2/jobs/{job_id}/stdout/?format=txt",
            headers=self.headers,
            verify=False
        )

        response.raise_for_status()

        return response.text
    
    def get_execution_url(self, job_id):
        return f"{self.base_url}/#/jobs/playbook/{job_id}/output"