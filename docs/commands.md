# Commands

There are a number of commands to manage your relay's database and config. You can add `--help` to
any category or command to get help on that specific option (ex. `activityrelay inbox --help`).

Note: `activityrelay` is only available via pip or pipx if `~/.local/bin` is in `$PATH`. If not,
use `python3 -m relay` if installed via pip or `~/.local/bin/activityrelay` if installed via pipx.


## Run

Run the relay.

	activityrelay run


## Setup

Run the setup wizard to configure your relay. For the PostgreSQL backend, the database has to be
created first.

	activityrelay setup


## Convert

Convert the old config and jsonld to the new config and SQL backend. If the old config filename is
not specified, the config will get backed up as `relay.backup.yaml` before converting.

	activityrelay convert --old-config relaycfg.yaml


## Switch Backend

Change the database backend from the current one to the other. The config will be updated after
running the command.

Note: If switching to PostgreSQL, make sure the database exists first.

	activityrelay switch-backend


## Edit Config

Open the config file in a text editor. If an editor is not specified with `--editor`, the default
editor will be used.

	activityrelay edit-config --editor micro


## Config

Manage the relay config

	activityrelay config


### List

List the current config key/value pairs

	activityrelay config list


### Set

Set a value for a config option

	activityrelay config set <key> <value>


## User

### List

List all available users.

	activityrelay user list


### Create

Create a new user. You will be prompted for the new password.

	activityrelay user create <username> [associated ActivityPub handle]


### Delete

Delete a user.

	activityrelay user delete <username>


## Inbox

Manage the list of subscribed instances.


### List

List the currently subscribed instances or relays.

	activityrelay inbox list


### Add

Add an inbox to the database. If a domain is specified, it will default to `https://{domain}/inbox`.
If the added instance is not following the relay, expect errors when pushing messages.

	activityrelay inbox add <inbox or domain> --actor <actor url> --followid <follow activity ID> --software <nodeinfo software name>


### Remove

Remove an inbox from the database. An inbox or domain can be specified.

	activityrelay inbox remove <inbox or domain>


### Follow

Follow an instance or relay actor and add it to the database. If a domain is specified, it will
default to `https://{domain}/actor`.

	activityrelay inbox follow <actor or domain>

Note: The relay must be running for this command to work.


### Unfollow

Unfollow an instance or relay actor and remove it from the database. If the instance or relay does
not exist anymore, use the `inbox remove` command instead.

	activityrelay inbox unfollow <domain, actor, or inbox>

Note: The relay must be running for this command to work.


## Whitelist

Manage the whitelisted domains.


### List

List the current whitelist.

	activityrelay whitelist list


### Add

Add a domain to the whitelist.

	activityrelay whitelist add <domain>


### Remove

Remove a domain from the whitelist.

	activityrelay whitelist remove <domain>


### Import

Add all current inboxes to the whitelist.

	activityrelay whitelist import


## Ban

Manage the domain and software bans.


### List

List the current bans. Use `--only-domains` to display just the banned domains and `--only-software`
to just list the banned software. Specifying both will result in an error. `--expanded-format` will
put the reason on the next line.

	activityrelay instance list --only-domains --only-software --expanded-format


### Add

Add a domain or software to the ban list. If the instance is currently subscribed, it will be removed
from the relay.

	activityrelay ban add <name> --reason <text> --note <text> --software --fetch-nodeinfo


### Remove

Remove a ban.

	activityrelay ban remove <name> --software


### Update

Update the reason or note for a ban. Either `--reason` and/or `--note` must be specified.

	activityrelay ban update <name> --reason <text> --note <text> --software
