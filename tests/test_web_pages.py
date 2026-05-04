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
    assert b"The Duncan Trussell Family Hour" in response.content


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_rankings_page_loads() -> None:
    response = Client().get("/rankings/", {"rank": "hub"})

    assert response.status_code == 200
    assert b"Hub Rankings" in response.content


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
