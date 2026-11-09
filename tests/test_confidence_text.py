def test_align_handles_gufuding_level_claim():
    from deepchoice.utils.confidence_text import align_confidence_rationale
    text = "结论是条件性分支，故定为 medium：证据面只支持条件选择。"
    out = align_confidence_rationale(text, "low")
    assert "medium" not in out and "low" in out, out

