from __future__ import annotations

import re


CATEGORIES = {
    "EXCELLENT MATCH": "OTTIMA CORRISPONDENZA",
    "VERY GOOD MATCH": "OTTIMA OPZIONE",
    "GOOD MATCH": "BUONA OPZIONE",
    "POSSIBLE MATCH": "POSSIBILE OPZIONE",
    "LOW MATCH": "SCARSA CORRISPONDENZA",
    "PENDING VERIFICATION": "DA VERIFICARE",
}

MATCH_STATUSES = {
    "HIGH MATCH": "ALTA CORRISPONDENZA",
    "POSSIBLE MATCH": "POSSIBILE",
    "PENDING VERIFICATION": "DA VERIFICARE",
    "REJECTED": "ESCLUSO",
    "LOW MATCH": "SCARSA CORRISPONDENZA",
}

SOURCE_STATUSES = {
    "ACTIVE": "ATTIVA",
    "DEGRADED": "DEGRADATA",
    "BLOCKED": "BLOCCATA",
    "REQUIRES_AUTHENTICATION": "RICHIEDE ACCESSO",
    "UNSUPPORTED": "NON SUPPORTATA",
    "DISABLED": "DISATTIVATA",
}

REASONS = {
    "Total monthly cost and base rent are unavailable.": "Non sono disponibili né l'affitto né il costo mensile totale.",
    "Monthly cost is unavailable.": "Il costo mensile non è disponibile.",
    "No reliable bicycle route has been calculated.": "Non è stato possibile calcolare un percorso ciclabile affidabile.",
    "Independent studio/apartment.": "Monolocale o appartamento indipendente.",
    "Private room; housemate count is unknown.": "Stanza privata; il numero di coinquilini non è noto.",
    "Shared bedroom.": "Camera da letto condivisa.",
    "Accommodation type could not be established.": "La tipologia dell'alloggio non è stata determinata.",
    "Furnished.": "Arredato.",
    "Semi-furnished.": "Parzialmente arredato.",
    "Unfurnished.": "Non arredato.",
    "Availability date unknown.": "Data di disponibilità non indicata.",
    "BRP registration explicitly allowed.": "Registrazione BRP esplicitamente consentita.",
    "BRP registration explicitly prohibited.": "Registrazione BRP esplicitamente vietata.",
    "Cycling route is within the configured travel-time limit.": "Il tragitto in bici rientra nel limite impostato.",
    "Independent accommodation.": "Alloggio indipendente.",
    "Available immediately.": "Disponibile subito.",
    "BRP registration is explicitly allowed.": "La registrazione BRP è esplicitamente consentita.",
    "More than one other housemate is stated.": "Sono indicati più di un coinquilino.",
    "A shared bedroom does not meet the private-room requirement.": "La camera condivisa non soddisfa il requisito di stanza privata.",
    "Furnishing status unknown; provisional 4 points.": "Arredamento non specificato; assegnati provvisoriamente 4 punti.",
    "furnishing status": "stato dell'arredamento",
    "monthly rent and utilities": "affitto e utenze mensili",
    "utilities and mandatory monthly fees": "utenze e spese mensili obbligatorie",
    "confirmed all-inclusive monthly cost": "costo mensile totale confermato",
    "cycling travel time": "tempo di percorrenza in bici",
    "number of other housemates": "numero di altri coinquilini",
    "accommodation type": "tipologia dell'alloggio",
    "availability date": "data di disponibilità",
    "BRP registration permission": "permesso di registrazione BRP",
    "Listing is explicitly unavailable or already rented.": "L'alloggio risulta esplicitamente non disponibile o già affittato.",
    "Private room meets the maximum-one-housemate requirement.": "La stanza privata rispetta il limite di un altro coinquilino al massimo.",
    "Base rent is visible, but all-in budget fit needs verification.": "L'affitto base è indicato, ma il rispetto del budget totale va verificato.",
    "Confirmed monthly cost is within the configured maximum.": "Il costo mensile confermato rientra nel limite impostato.",
}

SOURCE_ERRORS = {
    "No listing cards recognized; source markup may have changed or the results are empty": "Non sono state riconosciute schede di annunci; la pagina potrebbe essere cambiata o non contenere risultati.",
    "No general supported personal rental-listing API was found. Use notifications/forwarding configured by the account owner.": "Non risulta disponibile un'API personale supportata per gli annunci. Usa le notifiche o l'inoltro configurati dal titolare dell'account.",
    "Current terms prohibit automated access and systematic extraction; use its own alerts or authorized email forwarding.": "I termini attuali vietano l'accesso automatico e l'estrazione sistematica. Usa gli avvisi del sito o l'inoltro autorizzato delle email.",
    "Current terms prohibit scraping/data mining without prior written permission; use Funda's own alerts or authorized email forwarding.": "I termini attuali vietano scraping e raccolta automatizzata senza autorizzazione scritta. Usa gli avvisi di Funda o l'inoltro autorizzato delle email.",
    "Public site describes itself as an aggregator and offers daily email alerts; automated reuse is not verified. Use its authorized email alert workflow.": "Il sito è un aggregatore e offre avvisi email giornalieri; non è stata verificata l'autorizzazione alla raccolta automatica. Usa il flusso ufficiale di avvisi email.",
    "No public API/feed found; listings are surfaced by its subscription service. Use user-authorized email alerts.": "Non è stata trovata un'API o un feed pubblico; gli annunci sono forniti tramite abbonamento. Usa gli avvisi email autorizzati dall'utente.",
    "Terms and supported automated access could not be verified; adapter remains disabled pending permission review.": "Non è stato possibile verificare i termini e l'accesso automatico consentito; la fonte resta disattivata in attesa di verifica.",
    "Full account access is required and no public API/feed was found; use the platform's own email alerts.": "Serve un account completo e non è stata trovata un'API o un feed pubblico. Usa gli avvisi email della piattaforma.",
    "Configure read-only IMAP credentials to ingest platform alerts; credentials are never logged.": "Configura l'accesso IMAP in sola lettura per importare gli avvisi email delle piattaforme. Le credenziali non vengono registrate nei log.",
}


def category_it(value: str | None) -> str:
    return CATEGORIES.get(value or "", value or "SCARSA CORRISPONDENZA")


def match_status_it(value: str | None) -> str:
    return MATCH_STATUSES.get(value or "", value or "DA VERIFICARE")


def source_status_it(value: str | None) -> str:
    return SOURCE_STATUSES.get(value or "", value or "SCONOSCIUTO")


def source_error_it(value: str | None) -> str | None:
    if not value:
        return None
    if value in SOURCE_ERRORS:
        return SOURCE_ERRORS[value]
    match = re.match(r"^HTTP (\d+); access controls are respected$", value)
    if match:
        return f"HTTP {match.group(1)}: accesso negato dal sito; richieste automatiche interrotte."
    match = re.match(r"^HTTP (\d+); paused for (\d+)s$", value)
    if match:
        return f"HTTP {match.group(1)}: fonte in pausa per {match.group(2)} secondi."
    match = re.match(r"^robots\.txt unavailable \(HTTP (\d+)\); adapter paused$", value)
    if match:
        return f"robots.txt non raggiungibile (HTTP {match.group(1)}); fonte messa in pausa."
    return value


def furnishing_it(value: str | None) -> str:
    return {
        "furnished": "Arredato",
        "semi-furnished": "Parzialmente arredato",
        "unfurnished": "Non arredato",
        "unknown": "Non specificato",
    }.get((value or "unknown").lower(), value or "Non specificato")


def property_type_it(value: str | None) -> str:
    return {
        "studio": "Monolocale indipendente",
        "independent_apartment": "Appartamento indipendente",
        "private_room": "Stanza privata",
        "shared_bedroom": "Camera condivisa",
        "unknown": "Non specificata",
    }.get((value or "unknown").lower(), value or "Non specificata")


def reason_it(value: str | None) -> str:
    if not value:
        return "Dettaglio non disponibile."
    if value in REASONS:
        return REASONS[value]

    patterns: tuple[tuple[str, str], ...] = (
        (r"^€([\d,]+)/month all-inclusive\.$", r"€\1 al mese, tutto incluso."),
        (r"^Estimated total €([\d,]+)/month; estimate is not confirmed\.$", r"Totale stimato: €\1 al mese; importo non confermato."),
        (r"^€([\d,]+)/month base rent; utilities/fees are unknown\.$", r"Affitto base: €\1 al mese; utenze e spese non specificate."),
        (r"^Base rent is visible, but all-in budget fit needs verification\.$", "L'affitto base è indicato, ma il rispetto del budget totale va verificato."),
        (r"^Confirmed monthly cost is within the €([\d,]+) maximum\.$", r"Il costo mensile confermato rientra nel limite di €\1."),
        (r"^Base rent alone exceeds €([\d,]+); all-in cost cannot fit the configured budget\.$", r"Il solo affitto supera €\1; il costo totale non può rientrare nel budget impostato."),
        (r"^(\d+) minutes by bicycle \(approximate location\)\.$", r"\1 minuti in bici (località approssimativa)."),
        (r"^(\d+) minutes by bicycle\.$", r"\1 minuti in bici."),
        (r"^Private room with (\d+) other housemate\(s\)\.$", r"Stanza privata con \1 altri coinquilini."),
        (r"^Private room with (\d+) other housemates?\.$", r"Stanza privata con \1 altri coinquilini."),
        (r"^Furnishing status unknown; provisional (\d+) points\.$", r"Arredamento non specificato; assegnati provvisoriamente \1 punti."),
        (r"^Available within (\d+) days\.$", r"Disponibile entro \1 giorni."),
        (r"^Available in (-?\d+) days\.$", r"Disponibile tra \1 giorni."),
        (r"^BRP status unknown; provisional (\d+) points\.$", r"Stato BRP non specificato; assegnati provvisoriamente \1 punti."),
        (r"^(\d+)/5 required information dimensions documented\.$", r"Informazioni presenti: \1 dimensioni su 5."),
        (r"^Confirmed all-inclusive monthly cost €([\d,]+) exceeds €([\d,]+)\.$", r"Il costo mensile totale confermato di €\1 supera il limite di €\2."),
        (r"^Reliable cycling route is (\d+) minutes, over the (\d+)-minute limit\.$", r"Il percorso ciclabile affidabile dura \1 minuti, oltre il limite di \2 minuti."),
        (r"^Private room with (\d+) other housemates?\.$", r"Stanza privata con \1 altri coinquilini."),
    )
    for pattern, replacement in patterns:
        if re.match(pattern, value):
            return re.sub(pattern, replacement, value)
    return value


def confidence_it(value: float | int | None) -> str:
    percentage = 0 if value is None else round(float(value) * 100)
    level = "ALTA" if percentage >= 75 else "MEDIA" if percentage >= 40 else "BASSA"
    return f"{level} ({percentage}%)"


def cost_status_it(value: str | None) -> str:
    return {
        "CONFIRMED": "CONFERMATO",
        "ESTIMATED": "STIMATO",
        "BASE_ONLY": "SOLO AFFITTO BASE",
        "UNCONFIRMED": "DA CONFERMARE",
        "UNKNOWN": "SCONOSCIUTO",
    }.get((value or "UNKNOWN").upper(), value or "SCONOSCIUTO")
