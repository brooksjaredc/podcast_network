from podcast_network.data import LegacyRepository


def test_legacy_repository_loads_real_podcasts() -> None:
    repo = LegacyRepository()

    joe_rogan = repo.podcast(0)

    assert joe_rogan.name == "The Joe Rogan Experience"
    assert joe_rogan.hosts == ["Joe Rogan"]
    assert "Comedy" in joe_rogan.categories


def test_legacy_repository_loads_real_people() -> None:
    repo = LegacyRepository()

    joe_rogan = next(person for person in repo.people if person.name == "Joe Rogan")

    assert joe_rogan.id == 0
    assert joe_rogan.pr_rank > 0
