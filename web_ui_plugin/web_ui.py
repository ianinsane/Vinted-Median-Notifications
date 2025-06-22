from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from functools import wraps
import db, core, os, re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime
from logger import get_logger
import configuration_values
from dotenv import load_dotenv

# Get logger for this module
logger = get_logger(__name__)

# Create Flask app
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'),
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'))

# Secret key for session management
app.secret_key = os.urandom(24)

# Load .env file if present
load_dotenv()


# Auth-Helpers (müssen vor der Nutzung deklariert sein)
def check_auth(username, password):
    return username == os.environ.get('VINTED_UI_USER', 'admin') and password == os.environ.get('VINTED_UI_PASS', 'changeme')


def authenticate():
    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'
         }
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_version_info():
    is_up_to_date, current_ver, latest_version, github_url = core.check_version()
    return {
        'github_url': github_url,
        'current_version': current_ver,
        'latest_version': latest_version,
        'is_up_to_date': is_up_to_date
    }


@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}


def normalize_query_url(url):
    """Normalisiert einen Vinted-Query-String: Domain auf .fr, Parameter sortieren."""
    parsed = urlparse(url)
    # Domain auf .fr setzen
    netloc = 'www.vinted.fr'
    # Query-Parameter sortieren
    params = parse_qs(parsed.query, keep_blank_values=True)
    sorted_params = sorted(params.items())
    # Flache Liste für urlencode
    flat_params = []
    for k, v in sorted_params:
        for val in v:
            flat_params.append((k, val))
    new_query = urlencode(flat_params, doseq=True)
    normalized = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    return normalized


@app.route('/')
@requires_auth
def index():
    # Get parameters
    params = db.get_all_parameters()

    # Get queries
    queries = db.get_queries()
    formatted_queries = []
    for query in queries:
        parsed_query = urlparse(query[1])
        query_params = parse_qs(parsed_query.query)
        search_text = query_params.get('search_text', [None])[0]
        # Get the last timestamp for this query
        try:
            last_timestamp = db.get_last_timestamp(query[0])
            last_found_item = datetime.fromtimestamp(last_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        except:
            last_found_item = "Never"
        formatted_queries.append({
            'id': query[0],  # Echte DB-ID verwenden
            'query': query[0],  # Echte DB-ID für Links/Filter
            'display': search_text if search_text else query[1],
            'last_found_item': last_found_item,
            'name': query[3] if len(query) > 3 else ''
        })

    # Get recent items
    items = db.get_items(limit=10)
    formatted_items = []
    for item in items:
        formatted_items.append({
            'id': item[0],
            'title': item[1],
            'price': item[2],
            'currency': item[3],
            'timestamp': datetime.fromtimestamp(item[4]).strftime('%Y-%m-%d %H:%M:%S'),
            'query': item[5],
            'photo_url': item[6],
            # Korrekte Artikel-URL für Dashboard-Recent-Items
            'url': f'https://www.vinted.fr/items/{item[0]}'
        })

    # Get process status from the database
    telegram_running = db.get_parameter('telegram_process_running') == 'True'
    rss_running = db.get_parameter('rss_process_running') == 'True'

    # Get statistics for the dashboard
    stats = {
        'total_items': db.get_total_items_count(),
        'total_queries': db.get_total_queries_count(),
        'items_per_day': db.get_items_per_day()
    }

    # Get the last found item
    last_item = db.get_last_found_item()
    if last_item:
        stats['last_item'] = {
            'id': last_item[0],
            'title': last_item[1],
            'price': last_item[2],
            'currency': last_item[3],
            'timestamp': datetime.fromtimestamp(last_item[4]).strftime('%Y-%m-%d %H:%M:%S'),
            'query': last_item[5],
            'photo_url': last_item[6]
        }
    else:
        stats['last_item'] = None

    return render_template('index.html',
                           params=params,
                           queries=formatted_queries,
                           items=formatted_items,
                           telegram_running=telegram_running,
                           rss_running=rss_running,
                           stats=stats)


@app.route('/queries')
@requires_auth
def queries():
    all_queries = db.get_queries()
    formatted_queries = []
    for query in all_queries:
        parsed_query = urlparse(query[1])
        query_params = parse_qs(parsed_query.query)
        search_text = query_params.get('search_text', [None])[0]
        median_info = db.get_query_median_info(query[0])
        formatted_queries.append({
            'id': query[0],
            'query': query[0],  # Echte DB-ID für Links/Filter
            'display': search_text if search_text else query[1],
            'last_found_item': datetime.fromtimestamp(db.get_last_timestamp(query[0])).strftime('%Y-%m-%d %H:%M:%S') if db.get_last_timestamp(query[0]) else "Never",
            'name': query[3] if len(query) > 3 else '',
            'threshold_pct': query[4] if len(query) > 4 else 60,
            'poll_interval_s': query[5] if len(query) > 5 else 300,
            'active': bool(query[6]) if len(query) > 6 else True,
            'median_count': median_info['count'],
            'median_value': median_info['median'],
            'last_price': median_info['last_price']
        })
    return render_template('queries.html', queries=formatted_queries)


@app.route('/add_query', methods=['POST'])
@requires_auth
def add_query():
    query = request.form.get('query')
    if query:
        message, is_new_query = core.process_query(query)
        if is_new_query:
            flash(f'Query added: {query}', 'success')
        else:
            flash(message, 'warning')
    else:
        flash('No query provided', 'error')

    return redirect(url_for('queries'))


@app.route('/remove_query/<int:query_id>', methods=['POST'])
@requires_auth
def remove_query(query_id):
    message, success = core.process_remove_query(str(query_id))
    if success:
        flash('Query removed', 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('queries'))


@app.route('/remove_query/all', methods=['POST'])
@requires_auth
def remove_all_queries():
    message, success = core.process_remove_query("all")
    if success:
        flash('All queries removed', 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('queries'))


@app.route('/items')
@requires_auth
def items():
    query_id = request.args.get('query', '')  # Default to empty string instead of None
    limit = int(request.args.get('limit', 50))

    # Get items
    query_string = None
    threshold_pct = None
    median = None
    if query_id:
        # Get the actual query string and threshold for the given ID
        queries = db.get_queries()
        for q in queries:
            if str(q[0]) == query_id:
                query_string = normalize_query_url(q[1])
                threshold_pct = q[4] if len(q) > 4 and q[4] else 60
                median_info = db.get_query_median_info(q[0])
                median = median_info['median']
                break
    logger.info(f"[DEBUG] Query-ID: {query_id}, Query-String: {query_string}")
    # Extra debug: print all queries and their normalized forms
    queries = db.get_queries()
    for q in queries:
        logger.info(f"[DEBUG] DB Query ID: {q[0]}, Raw: {q[1]}, Normalized: {normalize_query_url(q[1])}")
    items_data = db.get_items(limit=limit, query=query_string)
    logger.info(f"[DEBUG] Items found before filter: {len(items_data)}")
    # Extra debug: print all item titles for this query
    for item in items_data:
        logger.info(f"[DEBUG] Item for Query-ID {query_id}: {item[1]} (Price: {item[2]})")
    formatted_items = []
    filtered_count = 0
    for item in items_data:
        # Filter by threshold if possible
        try:
            price_value = float(item[2])
        except Exception as e:
            logger.error(f"[ERROR] Could not convert price to float: {item[2]} (Item: {item[1]}) - {e}")
            continue
        if median is not None and threshold_pct is not None:
            if price_value > float(median) * (float(threshold_pct) / 100):
                filtered_count += 1
                continue
        formatted_items.append({
            'title': item[1],
            'price': price_value,
            'currency': item[3],
            'timestamp': datetime.fromtimestamp(item[4]).strftime('%Y-%m-%d %H:%M:%S'),
            'query': parse_qs(urlparse(item[5]).query).get('search_text', [''])[0] or '',
            'photo_url': item[6],
            'item_id': item[0],
            'raw_query': item[5],
            'url': f'https://www.vinted.fr/items/{item[0]}',
            'query_name': next((q[3] for q in queries if str(q[0]) == query_id), '') if query_id else ''
        })
    logger.info(f"[DEBUG] Items filtered out by threshold: {filtered_count}")
    logger.info(f"[DEBUG] Items after filter: {len(formatted_items)}")

    # Get queries for filter dropdown
    queries = db.get_queries()
    formatted_queries = []
    selected_query_display = None
    for i, q in enumerate(queries):
        parsed_query = urlparse(q[1])
        query_params = parse_qs(parsed_query.query)
        search_text = query_params.get('search_text', [None])[0]
        display_name = search_text if search_text else q[0]
        # Store display name for selected query
        if query_id == str(q[0]):
            selected_query_display = display_name
        formatted_queries.append({
            'id': i + 1,
            'query': str(q[0]),  # Ensure query is a string
            'display': display_name,
            'name': q[3] if len(q) > 3 else ''
        })

    return render_template('items.html',
                           items=formatted_items,
                           queries=formatted_queries,
                           selected_query=query_id,
                           selected_query_display=selected_query_display,
                           limit=limit)


@app.route('/config')
@requires_auth
def config():
    params = db.get_all_parameters()
    return render_template('config.html', params=params)


@app.route('/update_config', methods=['POST'])
@requires_auth
def update_config():
    # Update Telegram parameters
    telegram_enabled = 'telegram_enabled' in request.form
    db.set_parameter('telegram_enabled', str(telegram_enabled))
    db.set_parameter('telegram_token', request.form.get('telegram_token', ''))
    db.set_parameter('telegram_chat_id', request.form.get('telegram_chat_id', ''))

    # Update RSS parameters
    rss_enabled = 'rss_enabled' in request.form
    db.set_parameter('rss_enabled', str(rss_enabled))
    db.set_parameter('rss_port', request.form.get('rss_port', '8080'))
    db.set_parameter('rss_max_items', request.form.get('rss_max_items', '100'))

    # Update System parameters
    db.set_parameter('items_per_query', request.form.get('items_per_query', '20'))
    db.set_parameter('query_refresh_delay', request.form.get('query_refresh_delay', '60'))

    # Update Proxy parameters
    check_proxies = 'check_proxies' in request.form
    db.set_parameter('check_proxies', str(check_proxies))
    db.set_parameter('proxy_list', request.form.get('proxy_list', ''))
    db.set_parameter('proxy_list_link', request.form.get('proxy_list_link', ''))

    # Reset proxy cache to force refresh on next use
    db.set_parameter('last_proxy_check_time', "1")
    logger.info("Proxy settings updated, cache reset")

    flash('Configuration updated', 'success')
    return redirect(url_for('config'))


@app.route('/control/<process_name>/<action>', methods=['POST'])
@requires_auth
def control_process(process_name, action):
    if process_name not in ['telegram', 'rss']:
        return jsonify({'status': 'error', 'message': 'Invalid process name'})

    if action == 'start':
        if process_name == 'telegram':
            # Check current status
            if db.get_parameter('telegram_process_running') == 'True':
                return jsonify({'status': 'warning', 'message': 'Telegram bot already running'})

            # Check if telegram_token and telegram_chat_id are set
            telegram_token = db.get_parameter('telegram_token')
            telegram_chat_id = db.get_parameter('telegram_chat_id')
            if not telegram_token or not telegram_chat_id:
                return jsonify({'status': 'error',
                                'message': 'Please set Telegram token and chat ID in the configuration panel before starting the Telegram process'})

            # Update process status in the database
            # The manager process will detect this and start the process
            db.set_parameter('telegram_process_running', 'True')
            logger.info("Telegram bot process start requested")
            return jsonify({'status': 'success', 'message': 'Telegram bot start requested'})

        elif process_name == 'rss':
            # Check current status
            if db.get_parameter('rss_process_running') == 'True':
                return jsonify({'status': 'warning', 'message': 'RSS feed already running'})

            # Update process status in the database
            # The manager process will detect this and start the process
            db.set_parameter('rss_process_running', 'True')
            logger.info("RSS feed process start requested")
            return jsonify({'status': 'success', 'message': 'RSS feed start requested'})

    elif action == 'stop':
        if process_name == 'telegram':
            # Check current status
            if db.get_parameter('telegram_process_running') != 'True':
                return jsonify({'status': 'warning', 'message': 'Telegram bot not running'})

            # Update process status in the database
            # The manager process will detect this and stop the process
            db.set_parameter('telegram_process_running', 'False')
            logger.info("Telegram bot process stop requested")
            return jsonify({'status': 'success', 'message': 'Telegram bot stop requested'})

        elif process_name == 'rss':
            # Check current status
            if db.get_parameter('rss_process_running') != 'True':
                return jsonify({'status': 'warning', 'message': 'RSS feed not running'})

            # Update process status in the database
            # The manager process will detect this and stop the process
            db.set_parameter('rss_process_running', 'False')
            logger.info("RSS feed process stop requested")
            return jsonify({'status': 'success', 'message': 'RSS feed stop requested'})

    return jsonify({'status': 'error', 'message': 'Invalid action'})


@app.route('/control/status', methods=['GET'])
@requires_auth
def process_status():
    # Get process status from the database
    telegram_running = db.get_parameter('telegram_process_running') == 'True'
    rss_running = db.get_parameter('rss_process_running') == 'True'

    return jsonify({
        'telegram': telegram_running,
        'rss': rss_running
    })


@app.route('/allowlist')
@requires_auth
def allowlist():
    countries = db.get_allowlist()
    if countries == 0:
        countries = []

    return render_template('allowlist.html', countries=countries)


@app.route('/add_country', methods=['POST'])
@requires_auth
def add_country():
    country = request.form.get('country', '').strip()
    if country:
        message, country_list = core.process_add_country(country)
        flash(message, 'success' if 'added' in message else 'warning')
    else:
        flash('No country provided', 'error')

    return redirect(url_for('allowlist'))


@app.route('/remove_country/<country>', methods=['POST'])
@requires_auth
def remove_country(country):
    message, country_list = core.process_remove_country(country)
    flash(message, 'success')

    return redirect(url_for('allowlist'))


@app.route('/clear_allowlist', methods=['POST'])
@requires_auth
def clear_allowlist():
    db.clear_allowlist()
    flash('Allowlist cleared', 'success')

    return redirect(url_for('allowlist'))


@app.route('/logs')
@requires_auth
def logs():
    return render_template('logs.html')


@app.route('/api/logs')
def api_logs():
    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 100))
    level_filter = request.args.get('level', 'all')

    log_file_path = os.path.join('logs', 'vinted.log')

    if not os.path.exists(log_file_path):
        return jsonify({'logs': [], 'total': 0})

    # Parse log file
    log_entries = []
    total_matching_entries = 0

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='replace') as file:
            # Read all lines from the file
            all_lines = file.readlines()

            # Process lines in reverse order (newest first)
            all_lines.reverse()

            # Regular expression to parse log lines
            # Format: 2023-09-15 12:34:56,789 - module_name - LEVEL - Message
            log_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - ([^-]+) - ([A-Z]+) - (.+)'

            current_entry = 0

            for line in all_lines:
                match = re.match(log_pattern, line.strip())
                if match:
                    timestamp, module, level, message = match.groups()

                    # Apply level filter if specified
                    if level_filter != 'all' and level != level_filter:
                        continue

                    total_matching_entries += 1

                    # Skip entries before offset
                    if total_matching_entries <= offset:
                        continue

                    # Add entry if within limit
                    if current_entry < limit:
                        log_entries.append({
                            'timestamp': timestamp,
                            'module': module.strip(),
                            'level': level,
                            'message': message
                        })
                        current_entry += 1

                    # Stop if we've reached the limit
                    if current_entry >= limit:
                        break
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return jsonify({'logs': [], 'total': 0, 'error': str(e)})

    return jsonify({
        'logs': log_entries,
        'total': total_matching_entries
    })


@app.route('/edit_query/<int:query_id>', methods=['POST'])
@requires_auth
def edit_query(query_id):
    name = request.form.get('name')
    threshold_pct = request.form.get('threshold_pct')
    poll_interval_s = request.form.get('poll_interval_s')
    active = request.form.get('active')
    threshold_pct = int(threshold_pct) if threshold_pct else None
    poll_interval_s = int(poll_interval_s) if poll_interval_s else None
    active = 1 if active == '1' or active == 'on' else 0
    db.update_query_settings(query_id, name=name, threshold_pct=threshold_pct, poll_interval_s=poll_interval_s, active=active)
    flash('Query updated', 'success')
    return redirect(url_for('queries'))


@app.route('/healthz')
def health_check():
    try:
        # Check DB connection
        conn = db.get_db_connection()
        conn.execute('SELECT 1')
        conn.close()
        return jsonify({"status": "ok", "db": True}), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "error", "db": False, "error": str(e)}), 500


@app.route('/status')
def status():
    # System status: DB, Telegram, RSS, Uptime, Version
    import time
    import platform
    from datetime import datetime
    start_time = getattr(app, '_start_time', None)
    if not start_time:
        start_time = time.time()
        app._start_time = start_time
    uptime = int(time.time() - start_time)
    params = db.get_all_parameters()
    telegram_running = db.get_parameter('telegram_process_running') == 'True'
    rss_running = db.get_parameter('rss_process_running') == 'True'
    return jsonify({
        "status": "ok",
        "version": params.get('version'),
        "uptime_seconds": uptime,
        "telegram_running": telegram_running,
        "rss_running": rss_running,
        "system_time": datetime.now().isoformat(),
        "platform": platform.platform(),
        "python_version": platform.python_version()
    })


@app.route('/metrics')
def metrics():
    # Prometheus format: key value\n
    # Basic stats
    total_items = db.get_total_items_count()
    total_queries = db.get_total_queries_count()
    items_per_day = db.get_items_per_day()
    telegram_running = 1 if db.get_parameter('telegram_process_running') == 'True' else 0
    rss_running = 1 if db.get_parameter('rss_process_running') == 'True' else 0
    # Uptime
    import time
    start_time = getattr(app, '_start_time', None)
    if not start_time:
        start_time = time.time()
        app._start_time = start_time
    uptime = int(time.time() - start_time)
    # Compose metrics
    metrics = [
        f'vinted_total_items {total_items}',
        f'vinted_total_queries {total_queries}',
        f'vinted_items_per_day {items_per_day}',
        f'vinted_telegram_running {telegram_running}',
        f'vinted_rss_running {rss_running}',
        f'vinted_uptime_seconds {uptime}'
    ]
    return '\n'.join(metrics) + '\n', 200, {'Content-Type': 'text/plain; version=0.0.4'}


def web_ui_process():
    logger.info("Web UI process started")
    try:
        app.run(host='0.0.0.0', port=configuration_values.WEB_UI_PORT, debug=False)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Web UI process stopped")
    except Exception as e:
        logger.error(f"Error in web UI process: {e}", exc_info=True)
