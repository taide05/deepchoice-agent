from datetime import datetime

from deepchoice.security.redaction import redact_text, redact_value


def print_agent_output(output: object, agent: str = "AGENT") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    safe_agent = redact_text(agent, max_length=80)
    safe_output = (
        redact_text(output)
        if isinstance(output, str)
        else redact_text(redact_value(output))
    )
    print(f"[{ts}] [{safe_agent}] {safe_output}")
