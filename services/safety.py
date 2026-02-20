def validate_plan(plan: dict) -> dict:
    """
    Prevent dangerous or malformed execution.
    """

    if "mode" not in plan:
        raise ValueError("Invalid plan: missing mode")

    if plan["mode"] not in ["predefined", "dynamic"]:
        raise ValueError("Invalid mode")

    if plan["mode"] == "dynamic":
        steps = plan.get("dynamic_steps", [])

        if not isinstance(steps, list) or not steps:
            raise ValueError("Dynamic job requires steps")

        # Basic dangerous command filter
        blocked_keywords = ["rm -rf", "shutdown", "reboot", "mkfs", "dd "]

        for step in steps:
            for bad in blocked_keywords:
                if bad in step.lower():
                    raise ValueError(f"Blocked dangerous command: {bad}")

    return plan
