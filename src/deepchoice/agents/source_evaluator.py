from datetime import datetime


WEIGHTS = {
    "authority": 0.35,
    "timeliness": 0.25,
    "consistency": 0.20,
    "verifiability": 0.20,
}

AUTHORITY_MAP = {
    "official_doc": 10,
    "arxiv_paper": 10,
    "tech_blog": 7,
    "github": 6,
    "stackoverflow": 5,
    "reddit": 4,
    "anonymous": 2,
}

VERIFIABILITY_MAP = {
    "code": 10,
    "benchmark": 8,
    "citation": 6,
    "opinion": 2,
}


def classify_source_type(url: str, source: str) -> str:
    url_lower = url.lower()
    if "arxiv.org" in url_lower:
        return "arxiv_paper"
    if "github.com" in url_lower:
        return "github"
    if "stackoverflow.com" in url_lower or "stackexchange.com" in url_lower:
        return "stackoverflow"
    if "reddit.com" in url_lower:
        return "reddit"
    if source == "official" or "readthedocs" in url_lower or "docs." in url_lower:
        return "official_doc"
    if source == "chroma":
        return "official_doc"
    if "blog" in url_lower or "medium.com" in url_lower or "dev.to" in url_lower:
        return "tech_blog"
    return "tech_blog"


def classify_evidence_type(snippet: str) -> str:
    snip_lower = snippet.lower()
    if any(kw in snip_lower for kw in ["```", "def ", "import ", "pip install", "npm install"]):
        return "code"
    if any(kw in snip_lower for kw in ["benchmark", "throughput", "latency", "rps", "tokens/s"]):
        return "benchmark"
    if any(kw in snip_lower for kw in ["according to", "cited by", "reference", "[1]", "[2]"]):
        return "citation"
    if any(kw in snip_lower for kw in ["i think", "in my opinion", "i prefer", "i believe"]):
        return "opinion"
    return "citation"


def score_authority(source_type: str) -> int:
    return AUTHORITY_MAP.get(source_type, 4)


def score_timeliness(date_str: str | None) -> int:
    if not date_str:
        return 5
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        age = (datetime.now() - d).days
        if age < 90:
            return 10
        if age < 180:
            return 8
        if age < 365:
            return 6
        if age < 730:
            return 4
        return 2
    except (ValueError, TypeError):
        return 5


def score_consistency(supporting_sources: list[str], has_contradiction: bool = False) -> int:
    if has_contradiction:
        return 2
    if len(supporting_sources) >= 2:
        return 10
    if len(supporting_sources) == 1:
        return 6
    return 4


def score_verifiability(evidence_type: str) -> int:
    return VERIFIABILITY_MAP.get(evidence_type, 4)


def compute_total_score(scores: dict[str, int]) -> float:
    return round(
        scores["authority"] * WEIGHTS["authority"]
        + scores["timeliness"] * WEIGHTS["timeliness"]
        + scores["consistency"] * WEIGHTS["consistency"]
        + scores["verifiability"] * WEIGHTS["verifiability"],
        1,
    )


class SourceEvaluatorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        all_results = []
        for channel in research_state.get("search_results", []):
            source = channel.get("source", "unknown")
            for r in channel.get("results", []):
                all_results.append({**r, "_source": source})

        source_scores = []
        for result in all_results:
            url = result.get("url", "")
            source = result.get("_source", "unknown")
            source_type = classify_source_type(url, source)
            evidence_type = classify_evidence_type(result.get("snippet", ""))

            scores = {
                "authority": score_authority(source_type),
                "timeliness": score_timeliness(result.get("date")),
                "consistency": score_consistency([url]),
                "verifiability": score_verifiability(evidence_type),
            }
            total = compute_total_score(scores)

            source_scores.append({
                "url": url,
                "title": result.get("title", ""),
                "source_type": source_type,
                "evidence_type": evidence_type,
                "scores": scores,
                "total_score": total,
                "supporting_sources": [],
                "contradicting_sources": [],
            })

        source_scores.sort(key=lambda x: x["total_score"], reverse=True)
        for i, s in enumerate(source_scores):
            s["rank"] = i + 1

        for s in source_scores:
            similar = [
                x["url"] for x in source_scores
                if x["url"] != s["url"] and x["total_score"] >= 6.0
            ]
            s["supporting_sources"] = similar[:3]
            s["scores"]["consistency"] = score_consistency(similar)
            s["total_score"] = compute_total_score(s["scores"])

        source_scores.sort(key=lambda x: x["total_score"], reverse=True)
        for i, s in enumerate(source_scores):
            s["rank"] = i + 1

        avg_score = round(sum(s["total_score"] for s in source_scores) / len(source_scores), 1) if source_scores else 0

        return {
            "source_scores": source_scores,
            "quality_signals": [{
                "agent": "source_evaluator",
                "sources_scored": len(source_scores),
                "avg_score": avg_score,
                "high_score_count": sum(1 for s in source_scores if s["total_score"] >= 7.0),
                "low_score_count": sum(1 for s in source_scores if s["total_score"] < 5.0),
            }],
        }
