class ArticleBuilder:
    """
    Builds final article object before persistence.
    """

    def build(self, content: dict) -> dict:
        return {
            "topic": content.get("topic"),
            "title": content.get("topic"),
            "ru_content": content.get("ru_content"),
            "en_content": content.get("en_content"),
            "status": "published",
            "quality_score": content.get("quality_score", 0),
            "quality_approved": content.get(
                "quality_approved",
                False
            ),
            "source": content.get(
                "source",
                "unknown"
            ),
        }
