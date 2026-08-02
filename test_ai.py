from services.ai_engine.pipeline.content_pipeline import ContentPipeline

pipeline = ContentPipeline()

result = pipeline.generate_full_content("AI will replace 50% of jobs")

print("\n--- RAW RESULT ---\n")
print(result)
