import os
import time
import requests
from datetime import datetime
from .executor_interface import ExecutorInterface
from .rundeck import (
    build_job_yaml, build_group_job_yaml, build_validation_job_yaml,
    import_job, run_job, get_execution_state, get_execution_output,
    GROUP_ORDER
)


class RundeckExecutor(ExecutorInterface):

    # ─────────────────────────────────────────────────────
    # Original single-job run — preserved intact
    # ─────────────────────────────────────────────────────
    def run(self, ticket, plan, options, context):

        runtime_environment = options.get("environment")
        runtime_version     = options.get("version")

        commands = []
        for step in plan["steps"]:
            for cmd in step["commands"]:
                cmd = cmd.replace("{environment}",        "{{ environment }}")
                cmd = cmd.replace("{version}",             "{{ version }}")
                cmd = cmd.replace("{{ environment }}",     runtime_environment)
                cmd = cmd.replace("{{ version }}",         runtime_version)
                cmd = cmd.replace("${option.environment}", runtime_environment)
                cmd = cmd.replace("${option.version}",     runtime_version)
                commands.append(cmd)

        yaml_payload = build_job_yaml(ticket, plan, commands=commands)
        result       = import_job(yaml_payload)

        if not result.get("succeeded"):
            raise Exception(f"Rundeck job import failed: {result}")

        job_id    = result["succeeded"][0]["id"]
        execution = run_job(job_id, options=options)
        return execution

    # ─────────────────────────────────────────────────────
    # Run groups sequentially — one job per group
    # migration → bugfix → testing → feature → deployment
    # If any group fails → remaining groups are SKIPPED
    # After all succeed → post-deployment validation job runs
    # Teams notification sent after each group + final summary
    # ─────────────────────────────────────────────────────
    def run_groups(self, ticket, plan, options, context):

        groups  = plan.get("groups", [])
        ordered = sorted(groups, key=lambda g: GROUP_ORDER.get(g.get("type", "deployment"), 99))

        teams_url = os.getenv("TEAMS_WEBHOOK_URL", "")
        results   = []
        chain_ok  = True

        for group in ordered:
            group_name = group.get("name", "")
            group_type = group.get("type", "deployment")
            tickets    = group.get("tickets", [])

            if not chain_ok:
                results.append({
                    "group_name":    group_name,
                    "group_type":    group_type,
                    "tickets":       tickets,
                    "job_id":        None,
                    "execution_id":  None,
                    "execution_url": None,
                    "status":        "SKIPPED",
                    "logs":          [],
                    "error":         None,
                })
                self._notify_teams(teams_url, ticket, group_name, group_type,
                                   tickets, "⏭️ SKIPPED", options)
                continue

            try:
                # Build + import group job
                yaml_payload = build_group_job_yaml(ticket, group, options)
                import_result = import_job(yaml_payload)

                if not import_result.get("succeeded"):
                    raise Exception(f"Import failed: {import_result}")

                job_id    = import_result["succeeded"][0]["id"]
                execution = run_job(job_id, options=options)
                exec_id   = execution["id"]
                exec_url  = self.get_execution_url(exec_id)

                # Poll until complete
                final_state = self._poll(exec_id)
                logs        = get_execution_output(exec_id)
                status      = "SUCCEEDED" if final_state == "SUCCEEDED" else "FAILED"

                if status == "FAILED":
                    chain_ok = False

                results.append({
                    "group_name":    group_name,
                    "group_type":    group_type,
                    "tickets":       tickets,
                    "job_id":        job_id,
                    "execution_id":  exec_id,
                    "execution_url": exec_url,
                    "status":        status,
                    "logs":          logs.get("entries", []),
                    "error":         None,
                })

                emoji = "✅" if status == "SUCCEEDED" else "❌"
                self._notify_teams(teams_url, ticket, group_name, group_type,
                                   tickets, f"{emoji} {status}", options)

            except Exception as e:
                chain_ok = False
                results.append({
                    "group_name":    group_name,
                    "group_type":    group_type,
                    "tickets":       tickets,
                    "job_id":        None,
                    "execution_id":  None,
                    "execution_url": None,
                    "status":        "ERROR",
                    "logs":          [],
                    "error":         str(e),
                })
                self._notify_teams(teams_url, ticket, group_name, group_type,
                                   tickets, f"💥 ERROR: {str(e)[:100]}", options)

        # ── Post-deployment validation — only if all groups succeeded ──
        validation_result = None
        if chain_ok and groups:
            try:
                yaml_payload  = build_validation_job_yaml(ticket, plan, options)
                import_result = import_job(yaml_payload)

                if not import_result.get("succeeded"):
                    raise Exception(f"Validation job import failed: {import_result}")

                job_id    = import_result["succeeded"][0]["id"]
                execution = run_job(job_id, options=options)
                exec_id   = execution["id"]
                exec_url  = self.get_execution_url(exec_id)

                final_state = self._poll(exec_id)
                logs        = get_execution_output(exec_id)
                status      = "SUCCEEDED" if final_state == "SUCCEEDED" else "FAILED"

                validation_result = {
                    "group_name":    "Post-Deployment Validation",
                    "group_type":    "validation",
                    "tickets":       [ticket.get("key", "")],
                    "job_id":        job_id,
                    "execution_id":  exec_id,
                    "execution_url": exec_url,
                    "status":        status,
                    "logs":          logs.get("entries", []),
                    "error":         None,
                }

                emoji = "✅" if status == "SUCCEEDED" else "❌"
                self._notify_teams(
                    teams_url, ticket,
                    "Post-Deployment Validation", "validation",
                    [ticket.get("key", "")],
                    f"{emoji} VALIDATION {status}", options,
                    is_final=True,
                    all_results=results
                )

            except Exception as e:
                validation_result = {
                    "group_name":    "Post-Deployment Validation",
                    "group_type":    "validation",
                    "tickets":       [ticket.get("key", "")],
                    "job_id":        None,
                    "execution_id":  None,
                    "execution_url": None,
                    "status":        "ERROR",
                    "logs":          [],
                    "error":         str(e),
                }

        if validation_result:
            results.append(validation_result)

        return results

    # ─────────────────────────────────────────────────────
    # Poll execution until completed — max 30 attempts x 5s
    # ─────────────────────────────────────────────────────
    def _poll(self, execution_id: str, max_attempts: int = 30, interval: int = 5) -> str:
        for _ in range(max_attempts):
            state = get_execution_state(execution_id)
            if state.get("completed"):
                return state.get("executionState", "UNKNOWN")
            time.sleep(interval)
        return "UNKNOWN"

    # ─────────────────────────────────────────────────────
    # Send Teams notification for a group result
    # ─────────────────────────────────────────────────────
    def _notify_teams(
        self, webhook_url: str,
        ticket: dict,
        group_name: str, group_type: str,
        tickets: list, status_text: str,
        options: dict,
        is_final: bool = False,
        all_results: list = None
    ):
        if not webhook_url:
            return
        try:
            payload = {
                "change_id":   ticket.get("key", ""),
                "project":     ticket.get("project", ""),
                "group":       group_name,
                "group_type":  group_type,
                "tickets":     ", ".join(tickets),
                "status":      status_text,
                "environment": options.get("environment", ""),
                "version":     options.get("version", ""),
                "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            if is_final and all_results:
                summary_lines = [
                    f"{r['group_name']}: {r['status']}"
                    for r in all_results
                ]
                payload["summary"] = " | ".join(summary_lines)

            requests.post(webhook_url, json=payload, timeout=8)
        except Exception:
            pass  # never break execution chain for notification failure

    # ─────────────────────────────────────────────────────
    # Interface methods
    # ─────────────────────────────────────────────────────
    def get_status(self, execution_id):
        return get_execution_state(execution_id)

    def get_logs(self, execution_id):
        return get_execution_output(execution_id)

    def get_execution_url(self, execution_id):
        base    = os.getenv("RUNDECK_BASE_URL", "")
        project = os.getenv("RUNDECK_PROJECT", "")
        return f"{base}/project/{project}/execution/show/{execution_id}"