PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    authorized INTEGER NOT NULL DEFAULT 0,
    registered_at TEXT NOT NULL,
    last_interaction_at TEXT,
    preferences_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS activation_codes (
    code_hash TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'user',
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by INTEGER,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    adapter_type TEXT NOT NULL,
    status TEXT NOT NULL,
    polling_interval_seconds INTEGER NOT NULL,
    last_success_at TEXT,
    last_error TEXT,
    last_attempt_at TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    city TEXT,
    neighborhood TEXT,
    address TEXT,
    address_is_approximate INTEGER NOT NULL DEFAULT 0,
    base_rent_eur REAL,
    utilities_eur REAL,
    mandatory_fees_eur REAL,
    monthly_total_eur REAL,
    cost_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    utilities_included INTEGER,
    deposit_eur REAL,
    property_type TEXT NOT NULL DEFAULT 'unknown',
    bedrooms INTEGER,
    bathrooms INTEGER,
    housemates INTEGER,
    maximum_occupancy INTEGER,
    furnishing TEXT NOT NULL DEFAULT 'unknown',
    availability_date TEXT,
    registration TEXT NOT NULL DEFAULT 'unknown',
    minimum_duration TEXT,
    maximum_duration TEXT,
    income_requirements TEXT,
    student_eligibility TEXT,
    contract_type TEXT,
    agency_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    contact_url TEXT,
    application_instructions TEXT,
    image_urls_json TEXT NOT NULL DEFAULT '[]',
    latitude REAL,
    longitude REAL,
    cycling_minutes REAL,
    cycling_distance_m REAL,
    cycling_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
    route_provider TEXT,
    route_calculated_at TEXT,
    published_at TEXT,
    updated_at TEXT,
    availability_status TEXT NOT NULL DEFAULT 'available',
    first_detected_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    suitability_score INTEGER NOT NULL DEFAULT 0,
    score_category TEXT NOT NULL DEFAULT 'LOW MATCH',
    match_status TEXT NOT NULL DEFAULT 'PENDING VERIFICATION',
    data_confidence REAL NOT NULL DEFAULT 0,
    score_breakdown_json TEXT NOT NULL DEFAULT '{}',
    score_reasons_json TEXT NOT NULL DEFAULT '[]',
    missing_information_json TEXT NOT NULL DEFAULT '[]',
    hard_exclusions_json TEXT NOT NULL DEFAULT '[]',
    raw_data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS listing_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    external_id TEXT,
    original_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source_id, external_id),
    UNIQUE(source_id, original_url)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    telegram_message_id INTEGER,
    sent_at TEXT,
    status TEXT NOT NULL,
    score_snapshot_json TEXT NOT NULL DEFAULT '{}',
    change_details_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    UNIQUE(listing_id, telegram_user_id)
);

CREATE TABLE IF NOT EXISTS notification_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    event_key TEXT NOT NULL,
    telegram_message_id INTEGER,
    sent_at TEXT,
    status TEXT NOT NULL,
    score_snapshot_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    UNIQUE(listing_id, telegram_user_id, event_key)
);

CREATE TABLE IF NOT EXISTS user_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    interaction TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS route_cache (
    address_key TEXT PRIMARY KEY,
    latitude REAL,
    longitude REAL,
    geocode_status TEXT NOT NULL,
    cycling_minutes REAL,
    cycling_distance_m REAL,
    route_status TEXT NOT NULL,
    provider TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adapter_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_detected ON listings(first_detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(match_status, availability_status);
CREATE INDEX IF NOT EXISTS idx_listings_cost ON listings(monthly_total_eur);
CREATE INDEX IF NOT EXISTS idx_listing_sources_url ON listing_sources(original_url);
CREATE INDEX IF NOT EXISTS idx_notifications_sent ON notifications(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notification_history_sent ON notification_history(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_user ON user_interactions(telegram_user_id, created_at DESC);
