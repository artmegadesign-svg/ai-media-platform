class StrategyAgent:

    def analyze(self, topic: str) -> dict:
        if not topic:
            return {
                "topic": "",
                "audience": "",
                "angle": "",
                "content_type": "",
                "priority": "low",
                "keywords": []
            }

        topic_lower = topic.lower()

        audience = "general audience"
        priority = "medium"

        if any(word in topic_lower for word in [
            "business",
            "company",
            "automation",
            "sales"
        ]):
            audience = "business owners"
            priority = "high"

        return {
            "topic": topic,
            "audience": audience,
            "angle": "educational and practical",
            "content_type": "article",
            "priority": priority,
            "keywords": topic.split()[:5]
        }
