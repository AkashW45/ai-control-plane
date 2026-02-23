import subprocess
import tempfile
import yaml
import os


def translate_command(cmd: str):
    cmd = cmd.strip()

    # mkdir
    if cmd.startswith("mkdir "):
        path = cmd.replace("mkdir ", "").strip()
        return {
            "name": f"Ensure directory {path}",
            "file": {
                "path": path,
                "state": "directory"
            }
        }

    # touch
    if cmd.startswith("touch "):
        path = cmd.replace("touch ", "").strip()
        return {
            "name": f"Ensure file {path}",
            "file": {
                "path": path,
                "state": "touch"
            }
        }

    # echo "text" > file
    if cmd.startswith("echo ") and ">" in cmd:
        parts = cmd.split(">")
        content_part = parts[0].replace("echo", "").strip()
        dest = parts[1].strip()
        content = content_part.strip('"').strip("'")

        return {
            "name": f"Write content to {dest}",
            "copy": {
                "content": content,
                "dest": dest
            }
        }

    # fallback to command module
    return {
        "name": f"Run command: {cmd}",
        "command": cmd
    }


def build_playbook(ticket: dict, plan: dict):
    tasks = []

    for step in plan["steps"]:
        for cmd in step["commands"]:
            tasks.append(translate_command(cmd))

    playbook = [{
        "hosts": "localhost",
        "gather_facts": False,
        "vars": {
            "deploy_env": "QA",
            "version": ticket.get("fixVersion", "auto")
        },
        "tasks": tasks
    }]

    return yaml.dump(playbook, sort_keys=False)


def run_playbook(ticket: dict, plan: dict):
    playbook_yaml = build_playbook(ticket, plan)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yml") as tmp:
        tmp.write(playbook_yaml)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["ansible-playbook", tmp_path],
            capture_output=True,
            text=True
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    finally:
        os.remove(tmp_path)