# Riscy-PodMan

Riscy-PodMan is a terminal podcast download manager for RISC OS and Linux.

It is designed to stay simple:
- standard library only
- no `pip` packages
- plain terminal menus
- local JSON storage
- direct RSS and Atom feed support

Current script version: **v1.3**

## Features

- Add podcast feeds manually with an RSS or Atom URL
- Search for podcasts using **gpodder.net**
- Attempt recovery when a gpodder feed result is stale by scanning the podcast website for a working feed
- Refresh one feed or all feeds
- Download individual episodes or all undownloaded episodes
- Mark episodes as listened or unlistened
- View unlistened episodes across all podcasts
- Store podcast and episode data as JSON
- Use atomic JSON writes to reduce the chance of metadata corruption
- Apply per-host rate limiting for feed and media requests
- Handle redirects, retries, timeouts, and HTTP 429 rate limiting
- Skip expensive feed parse and merge work when the raw feed XML is unchanged, using a stored SHA-256 hash
- Support large feeds with a configurable feed XML size limit
- Use RISC OS-safe filename sanitisation and temporary file naming

## Requirements

- Python **3.4 or later**
- No third-party modules
- Network access to podcast feeds and search sources

## Running

### Linux

```bash
python3 riscypodman.py
```

### RISC OS

```text
python3 riscypodman/py
```

Or set the file type to `&FEB` and double-click it.

## Main menu

The program is menu-driven.

Typical commands from the main screen:

- `A` — Add podcast by feed URL
- `G` — Search for podcasts via gpodder.net
- `R` — Refresh all feeds
- `N` — Show new or unlistened episodes
- `S` — Settings
- `Q` — Quit
- number — Open a podcast

In most menus:
- type a number and press Enter to select
- type a letter command and press Enter
- press Enter on its own to go back or cancel

## Feed search with gpodder.net

Press `G` from the main menu to search for podcasts.

Search results show:
- podcast title
- website
- feed URL

From the results screen you can:
- enter a number to add a result directly
- use `V<n>` to inspect a result before adding it
- use `P` and `N` for paging
- use `S` for a new search
- use `B` to go back

### Stale feed recovery

Some directory entries point to feeds that have moved or been retired.

If adding a gpodder result fails, Riscy-PodMan can try to recover by:
1. visiting the podcast website
2. scanning the HTML for RSS or Atom links
3. scoring likely feed URLs
4. validating candidates until it finds a working feed

This does not guarantee recovery, but it helps with old Acast and moved-feed cases.

## Refresh behaviour

On startup, the program can refresh all feeds automatically if that option is enabled.

During refresh, the script:
- downloads the feed XML
- enforces a timeout and a maximum feed XML size
- hashes the raw XML with SHA-256
- skips parsing and merge work if the hash matches the last successful refresh

That means unchanged feeds can be checked quickly without repeatedly reparsing large XML documents.

## Downloads

Downloaded episodes are stored in a per-podcast directory under the configured download root.

Filename behaviour:
- titles are sanitised for the current platform
- the publication date is included where available
- part of the episode ID is appended to reduce collisions
- temporary files use a platform-safe suffix

## Settings

The current script includes these settings:

1. Download folder
2. Rate-limit delay
3. HTTP timeout
4. Max episodes per feed
5. Auto-refresh on start
6. Max feed XML size

### What they do

**Download folder**  
Root directory for downloaded episodes.

**Rate-limit delay**  
Minimum delay between requests to the same host.

**HTTP timeout**  
Socket timeout used for feed and media requests.

**Max episodes per feed**  
Maximum number of stored episodes per podcast after refresh and trim.

**Auto-refresh on start**  
If enabled, refreshes all feeds when the program launches.

**Max feed XML size**  
Upper bound for downloaded feed XML, useful for very large feeds such as some BBC podcast feeds.

## Storage locations

### Linux

Configuration and metadata are stored in:

```text
~/.config/podcastmanager
```

This includes:
- `config.json`
- `feeds.json`
- `episodes/`

Downloads default to:

```text
~/Podcasts
```

### RISC OS

Configuration is stored in:

```text
<Choices$Write>.RiscyPodMan
```

if `Choices$Write` is available.

If not, it falls back to a `Config` directory beside the script.

Downloads default to:

```text
<Home$Dir>.Podcasts
```

or the current working directory if `Home$Dir` is not set.

## Supported feed types

The script supports:
- RSS 2.0 podcast feeds
- Atom feeds with enclosure links

It also understands common podcast metadata such as:
- iTunes duration
- iTunes summary
- media content enclosures
- Dublin Core dates

## Notes on large or unusual feeds

Some feeds are very large, slow, or inconsistent.

This version includes:
- retry handling
- redirect handling
- HTTP 429 handling with `Retry-After`
- chunked feed reads
- a configurable XML size guardrail
- unchanged-feed hash skipping

If a feed still fails, try:
- increasing `Max feed XML size`
- increasing `HTTP timeout`
- refreshing the feed again later
- adding the feed manually instead of through search

## Limitations

- No audio playback is built in
- No streaming mode
- No background refresh daemon
- No OPML export or import yet
- Feed recovery from websites depends on the site exposing a detectable RSS or Atom link

## Example workflow

1. Start the program
2. Press `G`
3. Search for a podcast
4. Add it from the search results
5. Refresh feeds
6. Open a podcast by number
7. Download an episode with `D<n>`
8. Mark it listened with `L<n>`

## Troubleshooting

### Search result adds but the feed is gone

The program will try website-based feed discovery automatically for gpodder search results. If that still fails, add the feed manually with `A`.

### A feed appears to hang during refresh

This version should fail with a timeout or size warning instead of hanging silently. Raise `HTTP timeout` or `Max feed XML size` if needed.

### The same feed keeps refreshing with no changes

If the raw XML is unchanged, the script should report that the feed is unchanged and skip parse and merge work.

### RISC OS filenames look odd

That is expected. Characters unsafe for RISC OS paths are replaced so downloaded episode names remain usable.

## Development notes

The script is deliberately conservative and portable. It aims to run on older Python versions and to avoid outside dependencies.

Possible future improvements:
- OPML import and export
- local playback hooks
- per-feed refresh settings
- feed URL editing
- better duplicate detection across moved feeds
- optional caching of gpodder search results

## Licence

MIT
