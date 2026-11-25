from app.scrapers.base import PublicSearchAdapter


class ParariusAdapter(PublicSearchAdapter):
    source_id = "pararius"
    name = "Pararius"
    base_url = "https://www.pararius.com"
    interval = 120
    search_urls = (
        "https://www.pararius.com/apartments/amsterdam/studio",
        "https://www.pararius.com/apartments/amsterdam/room",
        "https://www.pararius.com/apartments/amsterdam/apartment",
    )
