import db, configuration_values, requests
from pyVintedVN import Vinted, requester
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

def normalize_query_url(url):
    """Normalisiert einen Vinted-Query-String: Domain auf .fr, Parameter sortieren."""
    parsed = urlparse(url)
    netloc = 'www.vinted.fr'
    params = parse_qs(parsed.query, keep_blank_values=True)
    sorted_params = sorted(params.items())
    flat_params = []
    for k, v in sorted_params:
        for val in v:
            flat_params.append((k, val))
    new_query = urlencode(flat_params, doseq=True)
    normalized = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    return normalized

def process_query(query):
    """
    Process a Vinted query URL by:
    1. Parsing the URL and extracting query parameters
    2. Ensuring the order flag is set to "newest_first"
    3. Removing time and search_id parameters
    4. Rebuilding the query string and URL
    5. Checking if the query already exists in the database
    6. Adding the query to the database if it doesn't exist

    Args:
        query (str): The Vinted query URL

    Returns:
        tuple: (message, is_new_query)
            - message (str): Status message
            - is_new_query (bool): True if query was added, False if it already existed
    """
    # Parse the URL and extract the query parameters
    parsed_url = urlparse(query)
    query_params = parse_qs(parsed_url.query)

    # Ensure the order flag is set to newest_first
    query_params['order'] = ['newest_first']
    # Remove time and search_id if provided
    query_params.pop('time', None)
    query_params.pop('search_id', None)
    query_params.pop('disabled_personalization', None)
    query_params.pop('page', None)

    searched_text = query_params.get('search_text')

    # Rebuild the query string and the entire URL
    new_query = urlencode(query_params, doseq=True)
    processed_query = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment))
    # Normalisierung anwenden
    processed_query = normalize_query_url(processed_query)

    # Some queries are made with filters only, so we need to check if the search_text is present
    if db.is_query_in_db(processed_query) is True:
        return "Query already exists.", False
    else:
        # add the query to the db
        db.add_query_to_db(processed_query)
        return "Query added.", True

def get_formatted_query_list():
    """
    Get a formatted list of all queries in the database.

    Returns:
        str: A formatted string with all queries, numbered
    """
    all_queries = db.get_queries()
    queries_keywords = []
    for query in all_queries:
        parsed_url = urlparse(query[1])
        query_params = parse_qs(parsed_url.query)

        # Extract the value of 'search_text'
        search_text = query_params.get('search_text', [None])

        if search_text[0] is None:
            # Use query text instead of the whole query object
            queries_keywords.append([query[1]])
        else:
            queries_keywords.append(search_text)

    query_list = ("\n").join([str(i + 1) + ". " + j[0] for i, j in enumerate(queries_keywords)])
    return query_list


def process_remove_query(number):
    """
    Process the removal of a query from the database.

    Args:
        number (str): The number of the query to remove or "all" to remove all queries

    Returns:
        tuple: (message, success)
            - message (str): Status message
            - success (bool): True if query was removed successfully
    """
    if number == "all":
        db.remove_all_queries_from_db()
        return "All queries removed.", True

    # Check if number is a valid digit
    if not number[0].isdigit():
        return "Invalid number.", False

    # Remove the query from the database
    db.remove_query_from_db(number)
    return "Query removed.", True


def process_add_country(country):
    """
    Process the addition of a country to the allowlist.

    Args:
        country (str): The country code to add

    Returns:
        tuple: (message, country_list)
            - message (str): Status message
            - country_list (list): Current list of allowed countries
    """
    # Format the country code (remove spaces)
    country = country.replace(" ", "")
    country_list = db.get_allowlist()

    # Validate the country code (check if it's 2 characters long)
    if len(country) != 2:
        return "Invalid country code", country_list

    # Check if the country is already in the allowlist
    # If country_list is 0, it means the allowlist is empty
    if country_list != 0 and country.upper() in country_list:
        return f'Country "{country.upper()}" already in allowlist.', country_list

    # Add the country to the allowlist
    db.add_to_allowlist(country.upper())
    return "Country added.", db.get_allowlist()


def process_remove_country(country):
    """
    Process the removal of a country from the allowlist.

    Args:
        country (str): The country code to remove

    Returns:
        tuple: (message, country_list)
            - message (str): Status message
            - country_list (list): Current list of allowed countries
    """
    # Format the country code (remove spaces)
    country = country.replace(" ", "")

    # Validate the country code (check if it's 2 characters long)
    if len(country) != 2:
        return "Invalid country code", db.get_allowlist()

    # Remove the country from the allowlist
    db.remove_from_allowlist(country.upper())
    return "Country removed.", db.get_allowlist()


def get_user_country(profile_id):
    """
    Get the country code for a Vinted user.

    Makes an API request to retrieve the user's country code.
    Handles rate limiting by trying an alternative endpoint.

    Args:
        profile_id (str): The Vinted user's profile ID

    Returns:
        str: The user's country code (2-letter ISO code) or "XX" if it can't be determined
    """
    # Users are shared between all Vinted platforms, so we can use whatever locale we want
    url = f"https://www.vinted.fr/api/v2/users/{profile_id}?localize=false"
    response = requester.get(url)
    # That's a LOT of requests, so if we get a 429 we wait a bit before retrying once
    if response.status_code == 429:
        # In case of rate limit, we're switching the endpoint. This one is slower, but it doesn't RL as soon. 
        # We're limiting the items per page to 1 to grab as little data as possible
        url = f"https://www.vinted.fr/api/v2/users/{profile_id}/items?page=1&per_page=1"
        response = requester.get(url)
        try:
            user_country = response.json()["items"][0]["user"]["country_iso_code"]
        except KeyError:
            logger.warning("Couldn't get the country due to too many requests. Returning default value.")
            user_country = "XX"
    else:
        user_country = response.json()["user"]["country_iso_code"]
    return user_country


def process_items(queue):
    """
    Process all queries from the database, search for items, and put them in the queue.
    Uses the global items_queue by default, but can accept a custom queue for backward compatibility.

    Args:
        queue (Queue, optional): The queue to put the items in. Defaults to the global items_queue.

    Returns:
        None
    """

    all_queries = db.get_queries()

    # Initialize Vinted
    vinted = Vinted()

    # Get the number of items per query from the database
    items_per_query = int(db.get_parameter("items_per_query"))

    for query in all_queries:
        all_items = vinted.items.search(query[1], nbr_items=items_per_query)
        logger.info(f"[DEBUG] Query: {query[1]} | Scraper returned {len(all_items)} items.")
        if all_items:
            logger.info(f"[DEBUG] First item sample: {all_items[0].__dict__ if hasattr(all_items[0], '__dict__') else str(all_items[0])}")
        # BYPASS is_new_item filter for troubleshooting
        data = list(all_items)
        logger.info(f"[DEBUG] Query: {query[1]} | After bypassing is_new_item filter: {len(data)} items.")
        queue.put((data, query[0]))
        logger.info(f"Scraped {len(data)} items for query: {query[1]}")


def clear_item_queue(items_queue, new_items_queue):
    """
    Process items from the items_queue.
    Implements Preis-Historie, Median, Threshold-Check, Duplikat-Filter gemäß PRD.
    """
    import time
    MIN_PRICES_FOR_MEDIAN = 10  # Mindestens 10 Preispunkte für Median-Berechnung
    if not items_queue.empty():
        data, query_id = items_queue.get()
        all_queries = db.get_queries()
        query_row = next((q for q in all_queries if q[0] == query_id), None)
        if query_row:
            threshold_pct = query_row[4] if len(query_row) > 4 and query_row[4] else 60
            active = query_row[6] if len(query_row) > 6 else 1
        else:
            threshold_pct = 60
            active = 1
        if not active:
            return
        for item in reversed(data):
            if db.is_item_seen(str(item.id)):
                logger.info(f"[DEBUG] Item {item.id} already seen, skipping.")
                continue
            last_query_timestamp = db.get_last_timestamp(query_id)
            if last_query_timestamp is not None and last_query_timestamp >= item.raw_timestamp:
                logger.info(f"[DEBUG] Item {item.id} older than last timestamp, skipping.")
                continue
            if db.get_allowlist() != 0 and (get_user_country(item.raw_data["user"]["id"])) not in (db.get_allowlist() + ["XX"]):
                db.update_last_timestamp(query_id, item.raw_timestamp)
                logger.info(f"[DEBUG] Item {item.id} not in allowlist, skipping.")
                continue
            # Use query-centric category_key for all price history
            category_key = f"query_{query_id}"
            db.add_price_history(category_key, item.price, item.raw_timestamp)
            prices = db.get_price_history(category_key)
            if len(prices) < MIN_PRICES_FOR_MEDIAN:
                # Preis-Historie aufbauen, noch keine Alerts, aber Preis speichern
                db.add_item_to_db(id=item.id, timestamp=item.raw_timestamp, price=item.price, title=item.title, photo_url=item.photo, query_id=query_id, currency=item.currency)
                db.add_seen_item(str(item.id), query_id, int(time.time()))
                logger.info(f"[DEBUG] Item {item.id} added to DB (building price history, not enough for median yet).")
                continue
            # Preis als float casten, robust gegen String/Float
            try:
                price_value = float(item.price)
            except Exception as e:
                logger.error(f"[ERROR] Could not convert item.price to float: {item.price} (Item: {item.id}) - {e}")
                continue
            median = db.get_median_price(category_key)
            if median is not None and price_value > float(median) * (float(threshold_pct) / 100):
                logger.info(f"[DEBUG] Item {item.id} price {price_value} above threshold (median {median}, threshold {threshold_pct}%), skipping.")
                continue
            db.add_seen_item(str(item.id), query_id, int(time.time()))
            db.add_item_to_db(id=item.id, timestamp=item.raw_timestamp, price=price_value, title=item.title, photo_url=item.photo, query_id=query_id, currency=item.currency)
            logger.info(f"[DEBUG] Item {item.id} added to DB and new_items_queue (below threshold or median ready).")
            content = configuration_values.MESSAGE.format(
                title=item.title,
                price=str(price_value) + " " + item.currency,
                brand=item.brand_title,
                image=None if item.photo is None else item.photo
            )
            new_items_queue.put((content, item.url, "Open Vinted", None, None))


def check_version():
    """
    Check if the application is up to date
    """
    try:
        # Get URL from the database
        github_url = db.get_parameter("github_url")
        # Get version from the database
        ver = db.get_parameter("version")
        # Get latest version from the repository
        url = f"{github_url}/releases/latest"
        response = requests.get(url)

        if response.status_code == 200:
            latest_version = response.url.split('/')[-1]
            is_up_to_date = (ver == latest_version)
            return is_up_to_date, ver, latest_version, github_url
        else:
            # If we can't check, assume it's up to date
            return True, ver, ver, github_url
    except Exception as e:
        logger.error(f"Error checking for new version: {str(e)}", exc_info=True)
        # If we can't check, assume it's up to date
        return True, ver, ver, github_url
