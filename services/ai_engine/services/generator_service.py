from services.ai_engine.pipeline.content_pipeline import ContentPipeline


class GeneratorService:

    def __init__(self):
        self.pipeline = ContentPipeline()


    def generate(self, topic: str) -> dict:

        result = self.pipeline.generate_full_content(topic)

        if result.get("status") == "rejected":
            return {
                "status": "rejected",
                "issues": result.get("issues", []),
                "ru_content": result.get("ru", ""),
                "en_content": result.get("en", "")
            }


        return {
            "status": "published",
            "id": result.get("id"),
            "title": result.get("title"),
            "ru_content": result.get("ru"),
            "en_content": result.get("en"),
            "quality_score": result.get("quality_score"),
            "quality_approved": result.get("quality_approved"),
            "quality_issues": result.get("quality_issues")
        }
