from services.ai_engine.pipeline.content_pipeline import ContentPipeline


class GeneratorService:

    def __init__(self):
        self.pipeline = ContentPipeline()


    def generate(self, topic: str, *, source_url: str | None = None,
                 source_content: str | None = None) -> dict:

        kwargs = {"source_url": source_url}
        if source_content:
            kwargs["source_content"] = source_content
        result = self.pipeline.generate_full_content(topic, **kwargs)

        if result.get("status") in {"duplicate", "reserved"}:
            return result

        if result.get("status") == "rejected":
            return {
                "status": "rejected",
                "issues": result.get("issues", []),
                "ru_content": result.get("ru", ""),
                "en_content": result.get("en", ""),
                "quality_score": result.get("quality_score"),
                "quality_approved": result.get("quality_approved"),
                "quality_issues": result.get("quality_issues"),
            }


        return {
            "post_created": result["post_created"],
            "status": "published",
            "id": result.get("id"),
            "title": result.get("title"),
            "topic": result.get("topic"),
            "ru_content": result.get("ru"),
            "en_content": result.get("en"),
            "quality_score": result.get("quality_score"),
            "quality_approved": result.get("quality_approved"),
            "quality_issues": result.get("quality_issues")
        }
