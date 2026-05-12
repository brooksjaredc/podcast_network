from django.test import Client, override_settings
from django.utils import timezone

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
    assert b"Guest Appearance Rankings" in response.content


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
def test_advanced_predictions_loads() -> None:
    response = Client().get("/advanced/predictions/")

    assert response.status_code == 200
    assert b"Future Link Predictions" in response.content
    assert b"plot.ly" not in response.content
    assert b"plots/predictions_histogram.html" in response.content
