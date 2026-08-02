class ContentBuilder:
    def build(self, ru: str, en: str) -> dict:
        return {
            "ru_post": ru,
            "en_post": en,
            "formats": {
                "telegram": ru,
                "twitter": ru.split("\n")[0] if ru else "",
                "seo": en
            }
        }
