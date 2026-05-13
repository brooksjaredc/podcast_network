from datetime import timedelta

from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from podcast_network.network_metrics import calculate_and_store_network_metrics
from podcast_network.web.catalog.models import Appearance, Episode, Person, Podcast
from podcast_network.web.explorer.services import database_six_degrees_graph


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
        published_at=timezone.now(),
    )
    second_episode = Episode.objects.create(
        podcast=second_podcast,
        guid="wtf-1",
        title="WTF with Common Guest",
        description="A conversation with Common Guest.",
        published_at=timezone.now(),
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
    assert b"Find the podcast path between almost anyone." in response.content
    assert b"home-path-form" in response.content
    assert b"home-network" in response.content


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
    assert b"class=\"path-graphic-svg\"" in response.content
    assert b"class=\"path-graphic-node path-graphic-node-person\"" in response.content
    assert b"class=\"path-graphic-node path-graphic-node-podcast\"" in response.content


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


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_links_people_and_podcasts() -> None:
    _, _, joe, _ = make_db_graph()
    response = Client().get("/rankings/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert f'href="/people/{joe.id}/"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_people_page_links_people_and_podcasts() -> None:
    _, _, joe, _ = make_db_graph()
    response = Client().get("/people/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert f'href="/people/{joe.id}/"'.encode() in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_page_links_podcasts_and_hosts() -> None:
    first_podcast, _, joe, _ = make_db_graph()
    response = Client().get("/podcasts/")

    assert response.status_code == 200
    assert f'href="/podcasts/{first_podcast.id}/"'.encode() in response.content
    assert b"The Joe Rogan Experience" in response.content
    assert b"Joe Rogan" in response.content
    assert b"Guest Appearances" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_detail_links_guests() -> None:
    first_podcast, _, joe, _ = make_db_graph()
    response = Client().get(f"/podcasts/{first_podcast.id}/")

    assert response.status_code == 200
    assert b"Hosts" in response.content
    assert b"Frequent Guests" in response.content
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

    assert graph._adjacency["Regular Panelist"]["Daily Panel"] == Appearance.Role.HOST
    assert "Prince" in graph.names


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_person_detail_loads() -> None:
    first_podcast, _, joe, _ = make_db_graph()
    response = Client().get(f"/people/{joe.id}/")

    assert response.status_code == 200
    assert b"Joe Rogan" in response.content
    assert b"Hosts or Co-hosts" in response.content
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
def test_recommendations_search_adds_selected_podcasts() -> None:
    first_podcast, _, _, _ = make_db_graph()
    response = Client().get("/recommendations/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert b"Recommendations" in response.content
    assert b"The Joe Rogan Experience" in response.content
    assert f'name="selected" value="{first_podcast.id}"'.encode() in response.content


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
    assert "Highest overlap rate" in content
    assert "100% overlap rate" in content
    assert content.index("Niche Match") < content.index("Broad Match")


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

    response = Client().get("/recommendations/", {"selected": str(first_podcast.id)})

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
    assert explanation_line.index("Zed Explanation") < explanation_line.index(
        "Alpha Explanation"
    )


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_advanced_predictions_loads() -> None:
    response = Client().get("/advanced/predictions/")

    assert response.status_code == 200
    assert b"Future Link Predictions" in response.content
    assert b"plot.ly" not in response.content
    assert b"plots/predictions_histogram.html" in response.content
