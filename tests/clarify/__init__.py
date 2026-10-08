def model_snapshot(query, **overrides):
    """Complete synthetic extraction reply; not evidence of model understanding."""
    return {"current_query": query, "scene": None, "complexity": None,
            "candidate_techs": [], "constraints": [], "unknown_techs": False,
            "action": "ask", "message": "Please clarify the missing requirement", **overrides}
