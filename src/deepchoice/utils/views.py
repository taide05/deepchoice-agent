from datetime import datetime


def print_agent_output(output: any, agent: str = "AGENT") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{agent}] {output}")
