-- name: get-config
SELECT * FROM config WHERE key = :key;


-- name: get-config-all
SELECT * FROM config;


-- name: put-config
INSERT INTO config (key, value, type)
VALUES (:key, :value, :type)
ON CONFLICT (key) DO UPDATE SET value = :value
RETURNING *;


-- name: del-config
DELETE FROM config
WHERE key = :key;


-- name: get-inbox
SELECT * FROM inboxes WHERE domain = :value or inbox = :value or actor = :value;


-- name: put-inbox
INSERT INTO inboxes (domain, actor, inbox, followid, software, accepted, created)
VALUES (:domain, :actor, :inbox, :followid, :software, :accepted, :created)
ON CONFLICT (domain) DO
UPDATE SET followid = :followid, inbox = :inbox, software = :software, created = :created
RETURNING *;


-- name: put-inbox-accept
UPDATE inboxes SET accepted = :accepted WHERE domain = :domain RETURNING *;


-- name: del-inbox
DELETE FROM inboxes
WHERE domain = :value or inbox = :value or actor = :value;


-- name: get-request
SELECT * FROM inboxes WHERE accepted = false and domain = :domain;


-- name: get-user
SELECT * FROM users
WHERE username = :value or handle = :value;


-- name: get-user-by-token
SELECT * FROM users
WHERE username = (
	SELECT user FROM apps
	WHERE token = :token
);


-- name: put-user
INSERT INTO users (username, hash, handle, created)
VALUES (:username, :hash, :handle, :created)
RETURNING *;


-- name: del-user
DELETE FROM users
WHERE username = :username or handle = :username;


-- name: get-app
SELECT * FROM apps
WHERE client_id = :id and client_secret = :secret;


-- name: get-app-with-token
SELECT * FROM apps
WHERE client_id = :id and client_secret = :secret and token = :token;


-- name: get-app-by-token
SELECT * FROM apps
WHERE token = :token;

-- name: del-app
DELETE FROM apps
WHERE client_id = :id and client_secret = :secret;


-- name: del-app-with-token
DELETE FROM apps
WHERE client_id = :id and client_secret = :secret and token = :token;


-- name: del-token-user
DELETE FROM apps WHERE "user" = :username;


-- name: get-software-ban
SELECT * FROM software_bans WHERE name = :name;


-- name: put-software-ban
INSERT INTO software_bans (name, reason, note, created)
VALUES (:name, :reason, :note, :created)
RETURNING *;


-- name: del-software-ban
DELETE FROM software_bans
WHERE name = :name;


-- name: get-domain-ban
SELECT * FROM domain_bans WHERE domain = :domain;


-- name: put-domain-ban
INSERT INTO domain_bans (domain, reason, note, created)
VALUES (:domain, :reason, :note, :created)
RETURNING *;


-- name: del-domain-ban
DELETE FROM domain_bans
WHERE domain = :domain;


-- name: get-domain-whitelist
SELECT * FROM whitelist WHERE domain = :domain;


-- name: put-domain-whitelist
INSERT INTO whitelist (domain, created)
VALUES (:domain, :created)
RETURNING *;


-- name: del-domain-whitelist
DELETE FROM whitelist
WHERE domain = :domain;


-- cache functions --

-- name: create-cache-table-sqlite
CREATE TABLE IF NOT EXISTS cache (
	id INTEGER PRIMARY KEY UNIQUE,
	namespace TEXT NOT NULL,
	key TEXT NOT NULL,
	"value" TEXT,
	type TEXT DEFAULT 'str',
	updated TIMESTAMP NOT NULL,
	UNIQUE(namespace, key)
);

-- name: create-cache-table-postgresql
CREATE TABLE IF NOT EXISTS cache (
	id SERIAL PRIMARY KEY,
	namespace TEXT NOT NULL,
	key TEXT NOT NULL,
	"value" TEXT,
	type TEXT DEFAULT 'str',
	updated TIMESTAMP NOT NULL,
	UNIQUE(namespace, key)
);


-- name: get-cache-item
SELECT * FROM cache
WHERE namespace = :namespace and key = :key;


-- name: get-cache-keys
SELECT key FROM cache
WHERE namespace = :namespace;


-- name: get-cache-namespaces
SELECT DISTINCT namespace FROM cache;


-- name: set-cache-item
INSERT INTO cache (namespace, key, value, type, updated)
VALUES (:namespace, :key, :value, :type, :date)
ON CONFLICT (namespace, key) DO
UPDATE SET value = :value, type = :type, updated = :date
RETURNING *;


-- name: del-cache-item
DELETE FROM cache
WHERE namespace = :namespace and key = :key;


-- name: del-cache-namespace
DELETE FROM cache
WHERE namespace = :namespace;


-- name: del-cache-all
DELETE FROM cache;
