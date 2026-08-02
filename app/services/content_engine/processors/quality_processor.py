class QualityProcessor:
    """
    Validates generated content quality before publishing.
    """

    REQUIRED_FIELDS = [
        "topic",
        "ru_content",
        "en_content",
    ]

    def process(self, content: dict) -> dict:
        issues = {}

        for field in self.REQUIRED_FIELDS:
            value = content.get(field)

            if not value or not isinstance(value, str) or not value.strip():
                issues[field] = "missing_or_empty"

        approved = len(issues) == 0

        content["quality_score"] = 100 if approved else 0
        content["quality_approved"] = approved
        content["quality_issues"] = issues

        return content
