from deepchoice.utils.dedup import deduplicate_results


class TestDedup:
    def test_empty_list(self):
        assert deduplicate_results([]) == []

    def test_single_result(self):
        results = [{"title": "Test", "snippet": "content"}]
        assert deduplicate_results(results) == results

    def test_duplicate_removed(self):
        results = [
            {"title": "A", "snippet": "LangGraph is a framework for building agents"},
            {"title": "B", "snippet": "LangGraph is a framework for building agents"},
            {"title": "C", "snippet": "Completely different topic here"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 2

    def test_all_unique(self):
        results = [
            {"title": "A", "snippet": "Python async programming guide"},
            {"title": "B", "snippet": "Rust memory safety explained"},
            {"title": "C", "snippet": "Kubernetes deployment tutorial"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 3
