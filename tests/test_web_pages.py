from django.test import Client, override_settings


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_home_page_loads() -> None:
    response = Client().get("/")

    assert response.status_code == 200
    assert b"Podcast Network" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_path_page_loads_real_query() -> None:
    response = Client().get("/path/", {"source": "Joe Rogan", "target": "Marc Maron"})

    assert response.status_code == 200
    assert b"The Joe Rogan Experience" in response.content
    assert b"path-entity-person" in response.content
    assert b"path-entity-podcast" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_path_page_suggestion_can_be_accepted() -> None:
    response = Client().get("/path/", {"source": "Barrack Obama", "target": "Marc Maron"})

    assert response.status_code == 200
    assert b"Yes, use this name" in response.content
    assert b'value="President Barack Obama"' in response.content
    assert b'value="Marc Maron"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_loads() -> None:
    response = Client().get("/rankings/", {"rank": "hub"})

    assert response.status_code == 200
    assert b"Hub Rankings" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_links_people_and_podcasts() -> None:
    response = Client().get("/rankings/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert b'href="/people/0/"' in response.content
    assert b'href="/podcasts/0/"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_people_page_links_people_and_podcasts() -> None:
    response = Client().get("/people/", {"q": "Joe Rogan"})

    assert response.status_code == 200
    assert b'href="/people/0/"' in response.content
    assert b'href="/podcasts/0/"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_page_links_podcasts_and_hosts() -> None:
    response = Client().get("/podcasts/")

    assert response.status_code == 200
    assert b'href="/podcasts/0/"' in response.content
    assert b'href="/people/0/"' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_podcast_detail_links_guests() -> None:
    response = Client().get("/podcasts/0/")

    assert response.status_code == 200
    assert b"Frequent Guests" in response.content
    assert b'href="/people/' in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_person_detail_loads() -> None:
    response = Client().get("/people/0/")

    assert response.status_code == 200
    assert b"Joe Rogan" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_common_guests_loads() -> None:
    response = Client().get("/common/", {"first": "0", "second": "1"})

    assert response.status_code == 200
    assert b"The Joe Rogan Experience" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_advanced_predictions_loads() -> None:
    response = Client().get("/advanced/predictions/")

    assert response.status_code == 200
    assert b"Future Link Predictions" in response.content
    assert b"plot.ly" not in response.content
    assert b"plots/predictions_histogram.html" in response.content
