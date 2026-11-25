from app.scrapers.base import PublicSearchAdapter


class IamExpatAdapter(PublicSearchAdapter):
    source_id = "iamexpat"
    name = "IamExpat"
    base_url = "https://www.iamexpat.nl"
    interval = 300
    search_urls = ("https://www.iamexpat.nl/housing/rental-properties/amsterdam",)


class VanderlindenAdapter(PublicSearchAdapter):
    source_id = "vanderlinden"
    name = "Van der Linden"
    base_url = "https://www.vanderlinden.nl"
    interval = 300
    search_urls = ("https://www.vanderlinden.nl/en/offer-rental-homes/",)


class VerhuurtBeterAdapter(PublicSearchAdapter):
    source_id = "verhuurtbeter"
    name = "VerhuurtBeter (Beter.nl request)"
    base_url = "https://verhuurtbeter.nl"
    interval = 300
    search_urls = ("https://verhuurtbeter.nl/en/housing",)


class HuurExpertAdapter(PublicSearchAdapter):
    source_id = "huurexpert"
    name = "HuurExpert"
    base_url = "https://www.huurexpert.nl"
    interval = 600
    search_urls = ("https://www.huurexpert.nl/huurwoning/amsterdam",)
