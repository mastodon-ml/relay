-- name: get-config
SELECT * FROM config WHERE key = :key


-- name: get-config-all
SELECT * FROM config


-- name: put-config
INSERT INTO config (key, value, type)
VALUES (:key, :value, :type)
ON CONFLICT (key) DO UPDATE SET value = :value
RETURNING *


-- name: del-config
DELETE FROM config
WHERE key = :key


-- name: get-inbox
SELECT * FROM inboxes WHERE domain = :value or inbox = :value or actor = :value


-- name: put-inbox
INSERT INTO inboxes (domain, actor, inbox, followid, software, created)
VALUES (:domain, :actor, :inbox, :followid, :software, :created)
ON CONFLICT (domain) DO UPDATE SET followid = :followid
RETURNING *


-- name: del-inbox
DELETE FROM inboxes
WHERE domain = :value or inbox = :value or actor = :value


-- name: get-software-ban
SELECT * FROM software_bans WHERE name = :name


-- name: put-software-ban
INSERT INTO software_bans (name, reason, note, created)
VALUES (:name, :reason, :note, :created)
RETURNING *


-- name: del-software-ban
DELETE FROM software_bans
WHERE name = :name


-- name: get-domain-ban
SELECT * FROM domain_bans WHERE domain = :domain


-- name: put-domain-ban
INSERT INTO domain_bans (domain, reason, note, created)
VALUES (:domain, :reason, :note, :created)
RETURNING *


-- name: del-domain-ban
DELETE FROM domain_bans
WHERE domain = :domain


-- name: get-domain-whitelist
SELECT * FROM whitelist WHERE domain = :domain


-- name: put-domain-whitelist
INSERT INTO whitelist (domain, created)
VALUES (:domain, :created)
RETURNING *


-- name: del-domain-whitelist
DELETE FROM whitelist
WHERE domain = :domain
