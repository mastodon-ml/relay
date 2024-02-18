# Configuration

## General

### Domain

Hostname the relay will be hosted on.

	domain: relay.example.com


### Listener

The address and port the relay will listen on. If the reverse proxy (nginx, apache, caddy, etc)
is running on the same host, it is recommended to change `listen` to `localhost` if the reverse
proxy is on the same host.

	listen: 0.0.0.0
	port: 8080


### Web Workers

The number of processes to spawn for handling web requests. Leave it at 0 to automatically detect
how many processes should be spawned.

	workers: 0


### Database type

SQL database backend to use. Valid values are `sqlite` or `postgres`.

	database_type: sqlite


### Cache type

Cache backend to use. Valid values are `database` or `redis`

	cache_type: database


### Sqlite File Path

Path to the sqlite database file. If the path is not absolute, it is relative to the config file.
directory.

	sqlite_path: relay.jsonld


## Postgresql

In order to use the Postgresql backend, the user and database need to be created first.

	sudo -u postgres psql -c "CREATE USER activityrelay WITH PASSWORD SomeSecurePassword"
	sudo -u postgres psql -c "CREATE DATABASE activityrelay OWNER activityrelay"


### Database Name

Name of the database to use.

	name: activityrelay


### Host

Hostname, IP address, or unix socket the server is hosted on.

	host: /var/run/postgresql


### Port

Port number the server is listening on.

	port: 5432


### Username

User to use when logging into the server.

	user: null


### Password

Password for the specified user.

	pass: null


## Redis

### Host

Hostname, IP address, or unix socket the server is hosted on.

	host: /var/run/postgresql


### Port

Port number the server is listening on.

	port: 5432


### Username

User to use when logging into the server.

	user: null


### Password

Password for the specified user.

	pass: null


### Database Number

Number of the database to use.

	database: 0


### Prefix

Text to prefix every key with. It cannot contain a `:` character.

	prefix: activityrelay
