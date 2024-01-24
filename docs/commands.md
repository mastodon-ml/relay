# Commands

There are a number of commands to manage your relay's database and config. You can add `--help` to
any category or command to get help on that specific option (ex. `activityrelay inbox --help`).

Note: `activityrelay` is only available via pip or pipx if `~/.local/bin` is in `$PATH`. If not,
use `python3 -m relay` if installed via pip or `~/.local/bin/activityrelay` if installed via pipx.


## Run

Run the relay.

	activityrelay run


## Setup

Run the setup wizard to configure your relay.

	activityrelay setup


## Convert

Convert the old config and jsonld to the new config and SQL backend. If the old config filename is
not specified, the config will get backed up as `relay.backup.yaml` before converting.

	activityrelay convert --old-config relaycfg.yaml


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


## Inbox

Manage the list of subscribed instances.


### List

List the currently subscribed instances or relays.

	activityrelay inbox list


### Add

Add an inbox to the database. If a domain is specified, it will default to `https://{domain}/inbox`.
If the added instance is not following the relay, expect errors when pushing messages.

	activityrelay inbox add <inbox or domain>


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


## Instance

Manage the instance ban list.


### List

List the currently banned instances.

	activityrelay instance list


### Ban

Add an instance to the ban list. If the instance is currently subscribed, it will be removed from
the inbox list.

	activityrelay instance ban <domain>


### Unban

Remove an instance from the ban list.

	activityrelay instance unban <domain>


### Update

Update the ban reason or note for an instance ban.

	activityrelay instance update bad.example.com --reason "the baddest reason"


## Software

Manage the software ban list. To get the correct name, check the software's nodeinfo endpoint.
You can find it at `nodeinfo['software']['name']`.


### List

List the currently banned software.

	activityrelay software list


### Ban

Add a software name to the ban list.

If `-f` or `--fetch-nodeinfo` is set, treat the name as a domain and try to fetch the software
name via nodeinfo.

If the name is `RELAYS` (case-sensitive), add all known relay software names to the list.

	activityrelay software ban [-f/--fetch-nodeinfo] <name, domain, or RELAYS>


### Unban

Remove a software name from the ban list.

If `-f` or `--fetch-nodeinfo` is set, treat the name as a domain and try to fetch the software
name via nodeinfo.

If the name is `RELAYS` (case-sensitive), remove all known relay software names from the list.

	activityrelay software unban [-f/--fetch-nodeinfo] <name, domain, or RELAYS>


### Update

Update the ban reason or note for a software ban. Either `--reason` and/or `--note` must be
specified.

	activityrelay software update relay.example.com --reason "begone relay"
