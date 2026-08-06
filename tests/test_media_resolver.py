from services.media.resolver import MediaResolver, MediaStrategy, MediaType


def _official(**overrides):
    metadata = {
        "news_type": "official_release",
        "material_type": "release_image",
        "verified_official_source": True,
        "source_url": "https://media.organization.example/releases/image.png",
        "official_domain": "organization.example",
        "origin": "organization_press_office",
        "license_type": "official_publication",
        "provenance": {"release_id": "release-42", "verified_by": "editor"},
    }
    metadata.update(overrides)
    return metadata


def test_normal_news_uses_generated_image():
    decision = MediaResolver().resolve(
        {"news_type": "news", "material_type": "image"}
    )
    assert decision.strategy is MediaStrategy.GENERATE_IMAGE


def test_third_party_article_image_is_rejected_even_with_a_url():
    decision = MediaResolver().resolve(
        {
            "material_type": "article_image",
            "source_url": "https://news.example/photo.jpg",
            "verified_official_source": True,
        }
    )
    assert decision.strategy is MediaStrategy.GENERATE_IMAGE


def test_unverified_image_falls_back():
    decision = MediaResolver().resolve(
        _official(verified_official_source=False)
    )
    assert decision.strategy is MediaStrategy.GENERATE_IMAGE


def test_official_release_image_is_allowed():
    decision = MediaResolver().resolve(_official())
    assert decision.strategy is MediaStrategy.USE_OFFICIAL_IMAGE
    assert decision.media_type is MediaType.IMAGE


def test_official_diagram_is_an_official_image():
    decision = MediaResolver().resolve(_official(material_type="diagram"))
    assert decision.strategy is MediaStrategy.USE_OFFICIAL_IMAGE


def test_official_infographic_is_allowed():
    decision = MediaResolver().resolve(_official(material_type="infographic"))
    assert decision.strategy is MediaStrategy.USE_OFFICIAL_INFOGRAPHIC
    assert decision.media_type is MediaType.INFOGRAPHIC


def test_official_pdf_is_allowed():
    decision = MediaResolver().resolve(
        _official(
            material_type="pdf",
            source_url="https://organization.example/report.pdf",
        )
    )
    assert decision.strategy is MediaStrategy.USE_OFFICIAL_DOCUMENT
    assert decision.media_type is MediaType.DOCUMENT


def test_official_video_with_matching_channel_is_allowed():
    decision = MediaResolver().resolve(
        _official(
            news_type="news",
            material_type="video",
            source_url="https://videos.example/watch/42",
            official_domain=None,
            publisher_identifier="org-channel",
            official_publisher_identifier="org-channel",
        )
    )
    assert decision.strategy is MediaStrategy.USE_OFFICIAL_VIDEO
    assert decision.media_type is MediaType.VIDEO


def test_third_party_video_reupload_falls_back():
    decision = MediaResolver().resolve(
        _official(
            material_type="video",
            official_domain=None,
            publisher_identifier="reupload-channel",
            official_publisher_identifier="org-channel",
        )
    )
    assert decision.strategy is MediaStrategy.GENERATE_IMAGE


def test_missing_and_conflicting_metadata_fall_back():
    resolver = MediaResolver()
    assert resolver.resolve(None).strategy is MediaStrategy.GENERATE_IMAGE
    conflicting = _official(official_domain="attacker.example")
    assert resolver.resolve(conflicting).strategy is MediaStrategy.GENERATE_IMAGE


def test_official_decision_preserves_origin_license_and_provenance():
    decision = MediaResolver().resolve(_official())
    assert decision.origin == "organization_press_office"
    assert decision.license_type == "official_publication"
    assert decision.source_url.endswith("/releases/image.png")
    assert decision.metadata["provenance"] == {
        "release_id": "release-42",
        "verified_by": "editor",
    }


def test_resolver_performs_no_network_or_integration_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external call attempted")

    monkeypatch.setattr("socket.create_connection", forbidden)
    decision = MediaResolver().resolve(_official())
    assert decision.strategy is MediaStrategy.USE_OFFICIAL_IMAGE
