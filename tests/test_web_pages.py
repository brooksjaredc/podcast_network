from datetime import UTC, datetime, timedelta

from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from podcast_network.network.metrics import calculate_and_store_network_metrics
from podcast_network.web.catalog.models import (
    Appearance,
    CanonicalPersonEntity,
    Episode,
    FutureLinkPrediction,
    FutureLinkPredictionRun,
    FutureLinkWeeklyAuditLink,
    FutureLinkWeeklyAuditRun,
    Person,
    Podcast,
)
from podcast_network.web.explorer.graph_service import database_six_degrees_graph


def make_db_graph() -> tuple[Podcast, Podcast, Person, Person]:
    first_podcast = Podcast.objects.create(
        name="The Joe Rogan Experience",
        description="Long-form conversations.",
        website_url="https://example.com/rogan",
    )
    second_podcast = Podcast.objects.create(
        name="WTF with Marc Maron",
        description="Interview podcast.",
        website_url="https://example.com/wtf",
    )
    joe = Person.objects.create(name="Joe Rogan", normalized_name="joe rogan")
    marc = Person.objects.create(name="Marc Maron", normalized_name="marc maron")
    barack = Person.objects.create(
        name="President Barack Obama",
        normalized_name="president barack obama",
    )
    shared_guest = Person.objects.create(name="Common Guest", normalized_name="common guest")
    first_episode = Episode.objects.create(
        podcast=first_podcast,
        guid="jre-1",
        title="Joe Rogan Experience with Marc Maron",
        description="Marc Maron joins Joe Rogan.",
        published_at=datetime(2024, 1, 15, tzinfo=UTC),
    )
    second_episode = Episode.objects.create(
        podcast=second_podcast,
        guid="wtf-1",
        title="WTF with Common Guest",
        description="A conversation with Common Guest.",
        published_at=datetime(2024, 2, 20, tzinfo=UTC),
    )
    for index in range(4):
        Episode.objects.create(
            podcast=first_podcast,
            guid=f"jre-extra-{index}",
            title=f"Extra JRE episode {index}",
        )
    Appearance.objects.create(
        episode=first_episode,
        person=joe,
        role=Appearance.Role.GUEST,
        source="test",
    )
    Appearance.objects.create(
        episode=first_episode,
        person=marc,
        role=Appearance.Role.GUEST,
        source="test",
    )
    Appearance.objects.create(
        episode=first_episode,
        person=shared_guest,
        role=Appearance.Role.GUEST,
        source="test",
    )
    Appearance.objects.create(
        episode=second_episode,
        person=barack,
        role=Appearance.Role.GUEST,
        source="test",
    )
    Appearance.objects.create(
        episode=second_episode,
        person=shared_guest,
        role=Appearance.Role.GUEST,
        source="test",
    )
    Appearance.objects.create(
        episode=first_episode,
        person=joe,
        role=Appearance.Role.HOST,
        source="test",
    )
    database_six_degrees_graph.cache_clear()
    return first_podcast, second_podcast, joe, marc


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_home_page_loads() -> None:
    response = Client().get("/")

    assert response.status_code == 200
    assert b"Six Degrees to Joe Rogan" in response.content
    assert b'href="https://brooksjaredc.github.io"' in response.content
    assert b"Created by Jared Brooks" in response.content
    assert b"Find the podcast path between almost anyone." in response.content
    assert b"home-path-form" in response.content
    assert b"Joe Rogan to Hillary Clinton" in response.content
    assert b"Conan O'Brien to Jordan Peterson" in response.content
    assert b"Oprah Winfrey to Bill Burr" in response.content
    assert b"home-hero-art" in response.content
    assert b"ChatGPT Image May 17" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_home_page_counts_visible_database_graph_nodes() -> None:
    make_db_graph()
    filtered_podcast = Podcast.objects.create(name="日本語番組")
    filtered_person = Person.objects.create(
        name="Filtered Person",
        normalized_name="filtered person",
    )
    filtered_episode = Episode.objects.create(
        podcast=filtered_podcast,
        guid="filtered-episode",
        title="Filtered Episode",
    )
    Appearance.objects.create(
        episode=filtered_episode,
        person=filtered_person,
        role=Appearance.Role.GUEST,
        source="test",
    )
    database_six_degrees_graph.cache_clear()

    response = Client().get("/")

    assert response.status_code == 200
    assert b"<strong>2</strong><span>podcasts</span>" in response.content
    assert b"<strong>4</strong><span>people</span>" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_path_page_loads_real_query() -> None:
    first_podcast, _, joe, marc = make_db_graph()
    response = Client().get("/path/", {"source": "Joe Rogan", "target": "Marc Maron"})

    assert response.status_code == 200
    assert b"The Joe Rogan Experience" in response.content
    assert b"path-entity-person" in response.content
    assert b"path-entity-podcast" in response.content
    assert f'href="/people/{joe.id}/"'.encode() in response.content
    assert f'href="/people/{marc.id}/"'.encode() in response.content
    assert f'href="/podcasts/{first_podcast.id}/"'.encode() in response.content
    assert b"data-path-graph" in response.content
    assert b"path_graph.js" in response.content
    assert b"Jan 15, 2024" in response.content
    assert b'name="start_date"' in response.content
    assert b'name="end_date"' in response.content
    assert b"Joe Rogan to Hillary Clinton" in response.content
    assert b"Conan O" in response.content
    assert b"Jordan Peterson" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_path_page_filters_by_date_window() -> None:
    make_db_graph()

    response = Client().get(
        "/path/",
        {
            "source": "Joe Rogan",
            "target": "Marc Maron",
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
        },
    )

    assert response.status_code == 200
    assert b"No connection found between Joe Rogan and Marc Maron." in response.content
    assert b'value="2023-01-01"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_path_page_suggestion_can_be_accepted() -> None:
    make_db_graph()
    response = Client().get("/path/", {"source": "Barrack Obama", "target": "Marc Maron"})

    assert response.status_code == 200
    assert b"Yes, use this name" in response.content
    assert b'value="President Barack Obama"' in response.content
    assert b'value="Marc Maron"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_loads() -> None:
    make_db_graph()
    response = Client().get("/rankings/", {"rank": "hub"})

    assert response.status_code == 200
    assert b"Hub Rankings" in response.content
    assert b"Metric Guide" in response.content
    assert b"Highlights people connected to other important people" in response.content
    assert b"Highlights hosts who receive links from prominent guests" in response.content
    assert b"Explore metric distribution charts" in response.content
    assert b"/advanced/metrics/" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_links_people_and_podcasts() -> None:
    _, _, joe, _ = make_db_graph()
    response = Client().get("/rankings/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert f'href="/people/{joe.id}/"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_empty_search_has_clear_action() -> None:
    make_db_graph()
    response = Client().get("/rankings/", {"q": "No Such Person", "rank": "appearances"})

    assert response.status_code == 200
    assert b"No people match this ranking search" in response.content
    assert b'href="/rankings/?rank=appearances"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_people_page_links_people_and_podcasts() -> None:
    _, _, joe, _ = make_db_graph()
    response = Client().get("/people/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert f'href="/people/{joe.id}/"'.encode() in response.content
    assert b"Search people" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_people_page_can_sort_by_podcast_count() -> None:
    make_db_graph()
    response = Client().get("/people/", {"sort": "podcasts"})

    assert response.status_code == 200
    assert b"Most podcasts" in response.content
    assert b'value="podcasts" selected' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_page_links_podcasts_and_hosts() -> None:
    first_podcast, _, joe, _ = make_db_graph()
    response = Client().get("/podcasts/")

    assert response.status_code == 200
    assert f'href="/podcasts/{first_podcast.id}/"'.encode() in response.content
    assert b"The Joe Rogan Experience" in response.content
    assert b"Joe Rogan" in response.content
    assert b"Guest Appearances" in response.content
    assert b"Search podcasts" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_page_filters_by_search_genre_and_activity() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    first_podcast.metadata = {"legacy": {"categories": ["Comedy"]}}
    first_podcast.save(update_fields=["metadata"])
    second_podcast.metadata = {"legacy": {"categories": ["News"]}}
    second_podcast.save(update_fields=["metadata"])
    first_podcast.episodes.update(published_at=timezone.now())
    second_podcast.episodes.update(published_at=timezone.now() - timedelta(days=90))

    response = Client().get(
        "/podcasts/",
        {
            "q": "Joe",
            "genre": "Comedy",
            "active": "1",
            "sort": "latest",
        },
    )

    assert response.status_code == 200
    assert b"The Joe Rogan Experience" in response.content
    assert b"WTF with Marc Maron" not in response.content
    assert b"Comedy" in response.content
    assert b'value="latest" selected' in response.content
    assert b'name="active" value="1" checked' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_detail_links_guests() -> None:
    first_podcast, _, joe, _ = make_db_graph()
    response = Client().get(f"/podcasts/{first_podcast.id}/")

    assert response.status_code == 200
    assert b"Hosts" in response.content
    assert b"Frequent Guests" in response.content
    assert b"podcast-detail-tab" in response.content
    assert b"Network-Based Guest Fits" in response.content
    assert b"Open the full predictions analysis" in response.content
    assert b"/advanced/predictions/" in response.content
    assert response.content.count(f'href="/people/{joe.id}/"'.encode()) == 1


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_detail_shows_genres() -> None:
    first_podcast, _, _, _ = make_db_graph()
    first_podcast.metadata = {"legacy": {"categories": ["Comedy", "Society & Culture"]}}
    first_podcast.save(update_fields=["metadata"])

    response = Client().get(f"/podcasts/{first_podcast.id}/")

    assert response.status_code == 200
    assert b"Podcast genres" in response.content
    assert b"Comedy" in response.content
    assert b"Society &amp; Culture" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_detail_hides_apple_genre_metadata() -> None:
    first_podcast, _, _, _ = make_db_graph()
    first_podcast.metadata = {"apple_podcasts": {"chart_sources": ["genre:1301"]}}
    first_podcast.save(update_fields=["metadata"])

    response = Client().get(f"/podcasts/{first_podcast.id}/")

    assert response.status_code == 200
    assert b"Apple:" not in response.content
    assert b"Apple genre" not in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_frequent_guest_is_listed_as_cohost_and_removed_from_guest_list() -> None:
    podcast = Podcast.objects.create(name="Daily Panel")
    regular = Person.objects.create(name="Regular Panelist", normalized_name="regular panelist")
    for index in range(101):
        episode = Episode.objects.create(
            podcast=podcast,
            guid=f"daily-panel-{index}",
            title=f"Episode {index}",
            published_at=timezone.now(),
        )
        Appearance.objects.create(
            episode=episode,
            person=regular,
            role=Appearance.Role.GUEST,
            source="test",
        )

    response = Client().get(f"/podcasts/{podcast.id}/")

    assert response.status_code == 200
    hosts_section = response.content.split(b"<h2>Frequent Guests</h2>")[0]
    guests_section = response.content.split(b"<h2>Frequent Guests</h2>")[1]
    assert b"Regular Panelist" in hosts_section
    assert b"Regular Panelist" not in guests_section


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_guest_on_more_than_twenty_percent_of_episodes_is_listed_as_cohost() -> None:
    podcast = Podcast.objects.create(name="Small Regular Show")
    regular = Person.objects.create(name="Small Show Regular", normalized_name="small show regular")
    for index in range(10):
        episode = Episode.objects.create(
            podcast=podcast,
            guid=f"small-regular-show-{index}",
            title=f"Episode {index}",
            published_at=timezone.now(),
        )
        if index < 3:
            Appearance.objects.create(
                episode=episode,
                person=regular,
                role=Appearance.Role.GUEST,
                source="test",
            )

    response = Client().get(f"/podcasts/{podcast.id}/")

    assert response.status_code == 200
    hosts_section = response.content.split(b"<h2>Frequent Guests</h2>")[0]
    guests_section = response.content.split(b"<h2>Frequent Guests</h2>")[1]
    assert b"Small Show Regular" in hosts_section
    assert b"Small Show Regular" not in guests_section


def test_database_graph_treats_frequent_guest_as_host_and_keeps_single_names() -> None:
    podcast = Podcast.objects.create(name="Daily Panel")
    regular = Person.objects.create(name="Regular Panelist", normalized_name="regular panelist")
    prince = Person.objects.create(name="Prince", normalized_name="prince")
    for index in range(101):
        episode = Episode.objects.create(
            podcast=podcast,
            guid=f"daily-panel-graph-{index}",
            title=f"Episode {index}",
        )
        Appearance.objects.create(
            episode=episode,
            person=regular,
            role=Appearance.Role.GUEST,
            source="test",
        )
    single_episode = Episode.objects.create(
        podcast=podcast,
        guid="daily-panel-single",
        title="Single Name Episode",
    )
    Appearance.objects.create(
        episode=single_episode,
        person=prince,
        role=Appearance.Role.GUEST,
        source="test",
    )
    database_six_degrees_graph.cache_clear()

    graph = database_six_degrees_graph()

    assert graph.edge_kind("Regular Panelist", "Daily Panel") == Appearance.Role.HOST
    assert "Prince" in graph.names


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_person_detail_loads() -> None:
    first_podcast, _, joe, _ = make_db_graph()
    response = Client().get(f"/people/{joe.id}/")

    assert response.status_code == 200
    assert b"Joe Rogan" in response.content
    assert b"Hosts or Co-hosts" in response.content
    assert b"Network Snapshot" in response.content
    assert b"Find path to Joe Rogan" in response.content
    assert b"person-detail-tab" in response.content
    assert b"Open the full predictions analysis" in response.content
    assert b"/advanced/predictions/" in response.content
    assert b"The Joe Rogan Experience" in response.content
    assert f'href="/podcasts/{first_podcast.id}/"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_person_detail_shows_network_rankings() -> None:
    _, _, _, marc = make_db_graph()
    call_command("sync_person_entities")
    calculate_and_store_network_metrics()

    response = Client().get(f"/people/{marc.id}/")

    assert response.status_code == 200
    assert b"Network Rankings" in response.content
    assert b"PageRank" in response.content
    assert b"Hub" in response.content
    assert b"Authority" in response.content
    assert b"Betweenness centrality" in response.content
    assert b'href="/rankings/?rank=pr"' in response.content
    assert b"#" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_common_guests_loads() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    response = Client().get(
        "/common/",
        {"first": str(first_podcast.id), "second": str(second_podcast.id)},
    )

    assert response.status_code == 200
    assert b"The Joe Rogan Experience" in response.content
    assert b"Common Guest" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_common_guests_ignores_invalid_query_ids() -> None:
    response = Client().get("/common/", {"first": "not-an-id", "second": "2"})

    assert response.status_code == 200
    assert b"Compare Podcasts" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_common_guests_prompts_for_second_podcast() -> None:
    first_podcast, _, _, _ = make_db_graph()
    response = Client().get("/common/", {"first": str(first_podcast.id)})

    assert response.status_code == 200
    assert b"Choose a second podcast" in response.content
    assert b"Choose second podcast" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_search_adds_selected_podcasts() -> None:
    first_podcast, _, _, _ = make_db_graph()
    response = Client().get("/recommendations/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert b"Recommendations" in response.content
    assert b"The Joe Rogan Experience" in response.content
    assert f'name="selected" value="{first_podcast.id}"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_show_genre_filters_before_selection() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    first_podcast.metadata = {"legacy": {"categories": ["Comedy"]}}
    first_podcast.save(update_fields=["metadata"])
    second_podcast.metadata = {"legacy": {"categories": ["Society & Culture"]}}
    second_podcast.save(update_fields=["metadata"])

    response = Client().get("/recommendations/")

    assert response.status_code == 200
    assert b"All genres" in response.content
    assert b"Comedy" in response.content
    assert b"Society &amp; Culture" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_rank_podcasts_by_shared_guests() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    response = Client().get("/recommendations/", {"selected": str(first_podcast.id)})

    assert response.status_code == 200
    assert b"Similar Podcasts" in response.content
    assert b"WTF with Marc Maron" in response.content
    assert b"Common Guest" in response.content
    assert b"Recommended because it shares" in response.content
    assert b"guests with The Joe Rogan Experience" in response.content
    assert f'href="/podcasts/{second_podcast.id}/"'.encode() in response.content
    assert f'name="selected" value="{second_podcast.id}"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_show_clear_button_for_selected_podcasts() -> None:
    first_podcast, _, _, _ = make_db_graph()
    response = Client().get(
        "/recommendations/",
        {"selected": str(first_podcast.id), "q": "Joe"},
    )

    assert response.status_code == 200
    assert b"Clear" in response.content
    assert b'name="q" value="Joe"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_filter_by_genre() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    second_podcast.metadata = {"legacy": {"categories": ["Comedy"]}}
    second_podcast.save(update_fields=["metadata"])

    response = Client().get(
        "/recommendations/",
        {"selected": str(first_podcast.id), "genre": "Comedy"},
    )

    assert response.status_code == 200
    assert b"WTF with Marc Maron" in response.content
    assert b"Comedy" in response.content
    assert b"All genres" in response.content
    assert b'class="pill-button active" type="submit">Comedy' in response.content
    assert b"<h3>Genres</h3>" in response.content
    assert b"<h3>Activity</h3>" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_filter_by_multiple_genres() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    shared_guest = Person.objects.get(name="Common Guest")
    second_podcast.metadata = {"legacy": {"categories": ["Comedy"]}}
    second_podcast.save(update_fields=["metadata"])
    third_podcast = Podcast.objects.create(
        name="Arts Interview Hour",
        metadata={"legacy": {"categories": ["Arts"]}},
    )
    episode = Episode.objects.create(
        podcast=third_podcast,
        guid="arts-1",
        title="Arts with Common Guest",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=episode,
        person=shared_guest,
        role=Appearance.Role.GUEST,
        source="test",
    )

    response = Client().get(
        "/recommendations/",
        {
            "selected": str(first_podcast.id),
            "genre": ["Comedy", "Arts"],
        },
    )

    assert response.status_code == 200
    assert b"WTF with Marc Maron" in response.content
    assert b"Arts Interview Hour" in response.content
    assert b'class="pill-button active" type="submit">Comedy' in response.content
    assert b'class="pill-button active" type="submit">Arts' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_hide_apple_genre_filters() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    second_podcast.metadata = {"apple_podcasts": {"chart_sources": ["genre:1301"]}}
    second_podcast.save(update_fields=["metadata"])

    response = Client().get("/recommendations/", {"selected": str(first_podcast.id)})

    assert response.status_code == 200
    assert b"WTF with Marc Maron" in response.content
    assert b"Apple:" not in response.content
    assert b"Apple genre" not in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_active_filter_excludes_old_podcasts() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    second_podcast.episodes.update(published_at=timezone.now() - timedelta(days=90))

    response = Client().get(
        "/recommendations/",
        {"selected": str(first_podcast.id), "active": "1"},
    )

    assert response.status_code == 200
    assert b"WTF with Marc Maron" not in response.content
    assert b'class="pill-button active" type="submit">Active in last 2 months' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_can_exclude_and_restore_podcasts() -> None:
    first_podcast, second_podcast, _, _ = make_db_graph()
    response = Client().get(
        "/recommendations/",
        {
            "selected": str(first_podcast.id),
            "excluded": str(second_podcast.id),
        },
    )

    assert response.status_code == 200
    recommendations_section = response.content.split(b"<h2>Similar Podcasts</h2>")[1]
    assert b"WTF with Marc Maron" not in recommendations_section
    assert b"Excluded" in response.content
    assert b"Restore" in response.content
    assert f'name="excluded" value="{second_podcast.id}"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_excluded_podcasts_downrank_similar_candidates() -> None:
    first_podcast, second_podcast, _, marc = make_db_graph()
    shared_guest = Person.objects.get(name="Common Guest")
    second_episode = second_podcast.episodes.first()
    assert second_episode is not None
    Appearance.objects.create(
        episode=second_episode,
        person=marc,
        role=Appearance.Role.GUEST,
        source="test",
    )
    similar_to_excluded = Podcast.objects.create(name="Similar To Excluded")
    similar_episode = Episode.objects.create(
        podcast=similar_to_excluded,
        guid="similar-excluded-1",
        title="Similar with Common and Marc",
        published_at=timezone.now(),
    )
    for person in [shared_guest, marc]:
        Appearance.objects.create(
            episode=similar_episode,
            person=person,
            role=Appearance.Role.GUEST,
            source="test",
        )

    cleaner_match = Podcast.objects.create(name="Cleaner Match")
    cleaner_episode = Episode.objects.create(
        podcast=cleaner_match,
        guid="cleaner-match-1",
        title="Cleaner with Joe",
        published_at=timezone.now(),
    )
    joe = Person.objects.get(name="Joe Rogan")
    Appearance.objects.create(
        episode=cleaner_episode,
        person=joe,
        role=Appearance.Role.GUEST,
        source="test",
    )

    response = Client().get(
        "/recommendations/",
        {
            "selected": str(first_podcast.id),
            "excluded": str(second_podcast.id),
        },
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Cleaner Match" in content
    assert "Similar To Excluded" in content
    assert content.index("Cleaner Match") < content.index("Similar To Excluded")
    assert "Down-ranked because it overlaps with excluded podcasts" in content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_can_sort_by_overlap_rate() -> None:
    first_podcast, _, joe, marc = make_db_graph()
    broad_match = Podcast.objects.create(name="Broad Match")
    broad_episode = Episode.objects.create(
        podcast=broad_match,
        guid="broad-match-1",
        title="Broad Match",
        published_at=timezone.now(),
    )
    for person in [joe, marc]:
        Appearance.objects.create(
            episode=broad_episode,
            person=person,
            role=Appearance.Role.GUEST,
            source="test",
        )
    for index in range(8):
        extra = Person.objects.create(
            name=f"Broad Extra {index}",
            normalized_name=f"broad extra {index}",
        )
        Appearance.objects.create(
            episode=broad_episode,
            person=extra,
            role=Appearance.Role.GUEST,
            source="test",
        )

    niche_match = Podcast.objects.create(name="Niche Match")
    niche_episode = Episode.objects.create(
        podcast=niche_match,
        guid="niche-match-1",
        title="Niche Match",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=niche_episode,
        person=joe,
        role=Appearance.Role.GUEST,
        source="test",
    )

    response = Client().get(
        "/recommendations/",
        {
            "selected": str(first_podcast.id),
            "sort": "rate",
        },
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Highest guest overlap" in content
    assert "100% overlap rate" in content
    assert content.index("Niche Match") < content.index("Broad Match")


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendations_default_to_highest_guest_overlap() -> None:
    first_podcast, _, joe, marc = make_db_graph()
    broad_match = Podcast.objects.create(name="Broad Match Default")
    broad_episode = Episode.objects.create(
        podcast=broad_match,
        guid="broad-match-default",
        title="Broad Match Default",
        published_at=timezone.now(),
    )
    for person in [joe, marc]:
        Appearance.objects.create(
            episode=broad_episode,
            person=person,
            role=Appearance.Role.GUEST,
            source="test",
        )
    for index in range(8):
        extra = Person.objects.create(
            name=f"Broad Default Extra {index}",
            normalized_name=f"broad default extra {index}",
        )
        Appearance.objects.create(
            episode=broad_episode,
            person=extra,
            role=Appearance.Role.GUEST,
            source="test",
        )

    niche_match = Podcast.objects.create(name="Niche Match Default")
    niche_episode = Episode.objects.create(
        podcast=niche_match,
        guid="niche-match-default",
        title="Niche Match Default",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=niche_episode,
        person=joe,
        role=Appearance.Role.GUEST,
        source="test",
    )

    response = Client().get("/recommendations/", {"selected": str(first_podcast.id)})

    assert response.status_code == 200
    content = response.content.decode()
    assert content.index("Highest guest overlap") < content.index("Most shared guests")
    assert content.index("Niche Match Default") < content.index("Broad Match Default")


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendation_shared_guests_sort_by_total_appearances() -> None:
    first_podcast, _, _, _ = make_db_graph()
    alpha = Person.objects.create(name="Alpha Guest", normalized_name="alpha guest")
    zed = Person.objects.create(name="Zed Guest", normalized_name="zed guest")
    for index in range(3):
        episode = Episode.objects.create(
            podcast=first_podcast,
            guid=f"selected-zed-{index}",
            title=f"Selected Zed {index}",
            published_at=timezone.now(),
        )
        Appearance.objects.create(
            episode=episode,
            person=zed,
            role=Appearance.Role.GUEST,
            source="test",
        )
    alpha_selected_episode = Episode.objects.create(
        podcast=first_podcast,
        guid="selected-alpha",
        title="Selected Alpha",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=alpha_selected_episode,
        person=alpha,
        role=Appearance.Role.GUEST,
        source="test",
    )

    candidate = Podcast.objects.create(name="Shared Guest Ordering")
    candidate_episode = Episode.objects.create(
        podcast=candidate,
        guid="shared-guest-ordering",
        title="Shared Guest Ordering",
        published_at=timezone.now(),
    )
    for person in [alpha, zed]:
        Appearance.objects.create(
            episode=candidate_episode,
            person=person,
            role=Appearance.Role.GUEST,
            source="test",
        )

    response = Client().get(
        "/recommendations/",
        {"selected": str(first_podcast.id), "sort": "overlap"},
    )

    assert response.status_code == 200
    card = response.content.decode().split("Shared Guest Ordering", 1)[1]
    shared_guest_line = card.split("Shared guests:", 1)[1]
    assert shared_guest_line.index("Zed Guest") < shared_guest_line.index("Alpha Guest")


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_recommendation_explanation_guests_sort_by_total_appearances() -> None:
    first_podcast, _, _, _ = make_db_graph()
    alpha = Person.objects.create(name="Alpha Explanation", normalized_name="alpha explanation")
    zed = Person.objects.create(name="Zed Explanation", normalized_name="zed explanation")
    for index in range(3):
        episode = Episode.objects.create(
            podcast=first_podcast,
            guid=f"selected-explanation-zed-{index}",
            title=f"Selected Explanation Zed {index}",
            published_at=timezone.now(),
        )
        Appearance.objects.create(
            episode=episode,
            person=zed,
            role=Appearance.Role.GUEST,
            source="test",
        )
    alpha_episode = Episode.objects.create(
        podcast=first_podcast,
        guid="selected-explanation-alpha",
        title="Selected Explanation Alpha",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=alpha_episode,
        person=alpha,
        role=Appearance.Role.GUEST,
        source="test",
    )

    candidate = Podcast.objects.create(name="Explanation Ordering")
    candidate_episode = Episode.objects.create(
        podcast=candidate,
        guid="explanation-ordering",
        title="Explanation Ordering",
        published_at=timezone.now(),
    )
    for person in [alpha, zed]:
        Appearance.objects.create(
            episode=candidate_episode,
            person=person,
            role=Appearance.Role.GUEST,
            source="test",
        )

    response = Client().get("/recommendations/", {"selected": str(first_podcast.id)})

    assert response.status_code == 200
    card = response.content.decode().split("Explanation Ordering", 1)[1]
    explanation_line = card.split("Recommended because", 1)[1].split("</p>", 1)[0]
    assert explanation_line.index("Zed Explanation") < explanation_line.index("Alpha Explanation")


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_advanced_predictions_loads() -> None:
    podcast = Podcast.objects.create(name="Prediction Test Podcast")
    person = Person.objects.create(
        name="Prediction Test Guest",
        normalized_name="prediction test guest",
    )
    episode = Episode.objects.create(
        podcast=podcast,
        guid="prediction-test-episode",
        title="Prediction Test Episode",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=episode,
        person=person,
        role=Appearance.Role.GUEST,
        source="test",
    )
    call_command("sync_person_entities")
    canonical = CanonicalPersonEntity.objects.create(
        am_entity_id="person_prediction_test_other",
        display_name="Prediction Other Guest",
        normalized_name="prediction other guest",
    )
    linked_canonical_id = person.observations.first().entity_link.canonical_id
    linked_canonical = CanonicalPersonEntity.objects.get(am_entity_id=linked_canonical_id)
    run = FutureLinkPredictionRun.objects.create(
        run_id="test-prediction-run",
        cutoff_at=timezone.now(),
        feature_names=["shared_neighbor_score", "guest_appearance_count"],
        score_histogram=[{"lower": 0.0, "upper": 0.1, "count": 1}],
        metadata={"score_histogram": [{"lower": 0.0, "upper": 0.1, "count": 1}]},
        candidate_count=1,
        scored_podcast_count=1,
        rows_written=1,
        max_degree=3,
    )
    FutureLinkPrediction.objects.create(
        run=run,
        rank=1,
        score=0.42,
        podcast=podcast,
        canonical=canonical,
        distance=3,
        features={"shared_neighbor_score": 5, "guest_appearance_count": 7},
    )
    audit_run = FutureLinkWeeklyAuditRun.objects.create(
        run_id="test-audit-run",
        week_start=timezone.now() - timedelta(days=7),
        week_end=timezone.now(),
        window_days=7,
        score_histogram=[{"lower": 0.0, "upper": 0.1, "count": 1}],
        metadata={"score_histogram": [{"lower": 0.0, "upper": 0.1, "count": 1}]},
        published_pair_count=1,
        new_link_count=1,
        scored_link_count=1,
        candidate_eligible_count=1,
        max_degree=3,
    )
    FutureLinkWeeklyAuditLink.objects.create(
        run=audit_run,
        rank=1,
        score=0.42,
        podcast=podcast,
        canonical=linked_canonical,
        link_published_at=timezone.now(),
        first_episode_published_at=timezone.now(),
        latest_episode_published_at=timezone.now(),
        distance=3,
        candidate_eligible=True,
    )

    response = Client().get("/advanced/predictions/")

    assert response.status_code == 200
    assert b"Network-Based Future Link Fits" in response.content
    assert b"plot.ly" not in response.content
    assert b"Score Distribution" in response.content
    assert b"Top Network Fits" in response.content
    assert f"/people/{person.id}/".encode() in response.content


def test_advanced_prediction_histogram_accepts_count_bins() -> None:
    from podcast_network.web.explorer.advanced.predictions import metadata_score_histogram_counts

    assert metadata_score_histogram_counts([1] * 100) == [10] * 10


@override_settings(ALLOWED_HOSTS=["testserver"], PLOT_ARTIFACT_GCS_URI="")
def test_advanced_pages_use_dynamic_plot_asset_route() -> None:
    response = Client().get("/advanced/map/")

    assert response.status_code == 200
    assert b"Network Map" in response.content
    assert b"/advanced/plots/network_podcasts.html" in response.content
    assert b"/static/plots/network_podcasts.html" not in response.content


@override_settings(ALLOWED_HOSTS=["testserver"], PLOT_ARTIFACT_GCS_URI="")
def test_advanced_landing_page_is_analysis_guide() -> None:
    response = Client().get("/advanced/")

    assert response.status_code == 200
    assert b"Analysis Guide" in response.content
    assert b"Open map" in response.content
    assert b"Read methods" in response.content
    assert b"/advanced/definitions/" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"], PLOT_ARTIFACT_GCS_URI="")
def test_map_page_uses_network_map_entry_point() -> None:
    response = Client().get("/map/")

    assert response.status_code == 200
    assert b"Network Map" in response.content
    assert b"Podcast Network Graph" in response.content
    assert b"People Network Graph" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"], PLOT_ARTIFACT_GCS_URI="")
def test_legacy_advanced_section_slugs_still_work() -> None:
    response = Client().get("/advanced/centrality/")

    assert response.status_code == 200
    assert b"Metric Distributions" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"], PLOT_ARTIFACT_GCS_URI="")
def test_plot_asset_route_serves_local_fallback() -> None:
    response = Client().get("/advanced/plots/plotly.min.js")

    assert response.status_code == 200
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert response["Content-Type"] in {"text/javascript", "application/javascript"}
    assert b"Plotly" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"], PLOT_ARTIFACT_GCS_URI="")
def test_plot_asset_route_rejects_unsafe_paths() -> None:
    response = Client().get("/advanced/plots/../settings.py")

    assert response.status_code == 404


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_detail_shows_future_link_predictions() -> None:
    podcast = Podcast.objects.create(name="Predicted Guest Podcast")
    person = Person.objects.create(name="Predicted Guest", normalized_name="predicted guest")
    episode = Episode.objects.create(
        podcast=podcast,
        guid="predicted-guest-source",
        title="Predicted Guest Source",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=episode,
        person=person,
        role=Appearance.Role.GUEST,
        source="test",
    )
    call_command("sync_person_entities")
    canonical = person.observations.first().entity_link.canonical
    run = FutureLinkPredictionRun.objects.create(
        run_id="podcast-detail-prediction-run",
        cutoff_at=timezone.now(),
        candidate_count=1,
        scored_podcast_count=1,
        rows_written=1,
        max_degree=3,
    )
    FutureLinkPrediction.objects.create(
        run=run,
        rank=1,
        score=0.77,
        podcast=podcast,
        canonical=canonical,
        distance=3,
        features={
            "shared_neighbor_score": 4,
            "host_bridge_count": 2,
            "guest_appearance_count": 9,
        },
    )

    response = Client().get(f"/podcasts/{podcast.id}/")

    assert response.status_code == 200
    assert b"Predicted Guest" in response.content
    assert f"/people/{person.id}/".encode() in response.content
    assert b"0.770" in response.content
    assert b"4 shared-neighbor signals" in response.content
    assert b"2 host bridges" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_person_detail_shows_future_link_predictions() -> None:
    podcast = Podcast.objects.create(name="Predicted Podcast")
    person = Person.objects.create(
        name="Podcast Prediction Person",
        normalized_name="podcast prediction person",
    )
    episode = Episode.objects.create(
        podcast=podcast,
        guid="podcast-prediction-source",
        title="Podcast Prediction Source",
        published_at=timezone.now(),
    )
    Appearance.objects.create(
        episode=episode,
        person=person,
        role=Appearance.Role.GUEST,
        source="test",
    )
    call_command("sync_person_entities")
    canonical = person.observations.first().entity_link.canonical
    run = FutureLinkPredictionRun.objects.create(
        run_id="person-detail-prediction-run",
        cutoff_at=timezone.now(),
        candidate_count=1,
        scored_podcast_count=1,
        rows_written=1,
        max_degree=3,
    )
    FutureLinkPrediction.objects.create(
        run=run,
        rank=1,
        score=0.88,
        podcast=podcast,
        canonical=canonical,
        distance=3,
        features={
            "shared_neighbor_score": 5,
            "guest_appearance_count": 12,
            "guest_days_since_latest_appearance": 30,
        },
    )

    response = Client().get(f"/people/{person.id}/")

    assert response.status_code == 200
    assert b"Predicted Podcast" in response.content
    assert f"/podcasts/{podcast.id}/".encode() in response.content
    assert b"0.880" in response.content
    assert b"5 shared-neighbor signals" in response.content
    assert b"12 prior guest appearances" in response.content
