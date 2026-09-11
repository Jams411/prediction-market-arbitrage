# Contract-discovery metadata provenance audit

Observed at: `2026-09-11T13:04:15Z`

Status: repository audit plus bounded unauthenticated public metadata observation.
No pair was approved and no matching threshold, ranking, registry, strategy, or
execution behavior changed.

## Sources

- Kalshi public `GET /markets`, `GET /markets/{ticker}`, `GET
  /events/{event_ticker}`, `GET /events/{event_ticker}/metadata`, `GET
  /series/{series_ticker}`, and official API reference/OpenAPI descriptions.
- Polymarket US public `GET /v1/markets`, `GET /v1/market/slug/{slug}`, `GET
  /v1/events`, `GET /v1/events/slug/{slug}`, and the official
  `Polymarket/polymarket-us-python` SDK types/resources.
- Repository discovery path: `scripts/discover_contract_pairs.py` and
  `pair_discovery/profiles.py`.

The observation used three ordinary Kalshi markets, one Kalshi multivariate
market, three Polymarket US markets, three Polymarket US events, and one detail
record for each relevant market/event/series surface. Only compact field names
and selected public semantic values were retained in this audit; raw responses
remain temporary and are not repository evidence.

## Availability and ingestion matrix

The classification describes the best public source plus the current discovery
profile, not whether the field alone proves equivalence.

| Field | Kalshi | Polymarket US |
|---|---|---|
| event identifier | AVAILABLE_AND_INGESTED (`event_ticker`, but used as opaque `underlying_event`) | AVAILABLE_NOT_INGESTED (event `id`/`slug`/`ticker`; market-list profile has no parent join) |
| series / league / category | AVAILABLE_NOT_INGESTED (event `series_ticker`/`category`; series `tags`) | AVAILABLE_BUT_LOSSY (market `category` ingested; event `seriesSlug`, tag league, team league dropped) |
| event title / name | AVAILABLE_NOT_INGESTED (event `title`/`sub_title`) | AVAILABLE_NOT_INGESTED (event `title`; profile substitutes often-generic market `question`) |
| market title / subtitle | AVAILABLE_BUT_LOSSY (`title` used; subtitle fields are not) | AVAILABLE_BUT_LOSSY (`title`/`question` used; `subtitle`/`titleShort` ignored) |
| participant / team / entity identifiers | AVAILABLE_BUT_LOSSY (`custom_strike`, documented `primary_participant_key`, MVE leg IDs; only `yes_sub_title` text used) | AVAILABLE_BUT_LOSSY (`teamId`, team provider IDs/name/league; only title text used) |
| event start time | AVAILABLE_AND_INGESTED (`occurrence_datetime`) | AVAILABLE_BUT_LOSSY (`gameStartTime` used; parent event `startTime`/`startDate` dropped and meaning can differ by market type) |
| market open / close time | AVAILABLE_NOT_INGESTED (`open_time`, `close_time`) | AVAILABLE_BUT_LOSSY (`startDate` ignored; `endDate` is mapped to settlement backstop rather than an explicit close field) |
| settlement / resolution time | AVAILABLE_BUT_LOSSY (`expiration_time` used; expected/latest expiration and timer dropped) | AVAILABLE_BUT_LOSSY (`endDate` used as backstop; parent event end fields dropped) |
| strike / threshold value | AVAILABLE_BUT_LOSSY (simple floor/cap types parsed; `between`, `structured`, `functional_strike`, and `custom_strike` dropped) | AVAILABLE_BUT_LOSSY (text heuristic only; no structured threshold observed in sampled market schema) |
| threshold inclusivity | AVAILABLE_BUT_LOSSY (derived from a subset of `strike_type`) | AVAILABLE_BUT_LOSSY (phrase heuristic) |
| measurement unit | AVAILABLE_BUT_LOSSY (keyword heuristic over rules) | AVAILABLE_BUT_LOSSY (keyword heuristic over question/description) |
| resolution source | AVAILABLE_BUT_LOSSY (structured event/series `settlement_sources` dropped; heuristic sentence retained) | AVAILABLE_BUT_LOSSY (event league `resolution` URL dropped; heuristic sentence retained) |
| detailed rules | AVAILABLE_BUT_LOSSY (`rules_primary`/`rules_secondary` selectively retained/extracted) | AVAILABLE_BUT_LOSSY (`description` selectively retained/extracted) |
| cancellation / postponement | AVAILABLE_BUT_LOSSY (sentence-keyword extraction) | AVAILABLE_BUT_LOSSY (sentence-keyword extraction) |
| void / refund treatment | AVAILABLE_BUT_LOSSY (sentence-keyword extraction can miss wording such as resolves to `$0.50`) | AVAILABLE_BUT_LOSSY (sentence-keyword extraction) |
| multiple-winner / champion treatment | AVAILABLE_BUT_LOSSY when stated in rules; otherwise UNKNOWN | AVAILABLE_BUT_LOSSY when stated in description; otherwise UNKNOWN |
| parent event relationship | AVAILABLE_AND_INGESTED (`event_ticker`, without event enrichment) | AVAILABLE_NOT_INGESTED (event responses contain nested markets; sampled market response omitted `eventSlug`) |
| market type | AVAILABLE_NOT_INGESTED (`market_type`; MVE fields separately available) | AVAILABLE_NOT_INGESTED (`marketType`, `sportsMarketType`, `sportsMarketTypeV2`, `comboEnabled`) |
| outcome labels | AVAILABLE_AND_INGESTED (`yes_sub_title`, `no_sub_title`) | AVAILABLE_AND_INGESTED (`marketSides[].description` plus `long`) |
| YES/NO mapping | AVAILABLE_BUT_LOSSY (subtitle mapping may be non-distinct; primary rule is not structurally mapped) | AVAILABLE_AND_INGESTED (`marketSides[].long` selects long/short labels independent of array order) |

## Confirmed drop points

1. Discovery calls only each venue's market-list endpoint and passes raw market
   objects directly to the profile functions. It does not use the domain market
   normalizers or perform parent-event/series enrichment.
2. Kalshi event title/subtitle, series/category/tags, competition/scope,
   structured settlement sources, contract URLs, custom strike participant IDs,
   and structured MVE identity/legs are therefore absent from comparison.
3. Polymarket US event ID/slug/title/date, series, tags/league/resolution source,
   nested parent relationship, and structured team/provider identifiers are
   absent from comparison even though public event responses expose them.
4. The lexical gate tokenizes only title, `underlying_event`, and participant
   text. Category is diagnostic-only. Kalshi contributes an opaque event ticker;
   Polymarket US contributes a frequently generic question, which explains why
   participant/team-name collisions dominate.

## Combo identification

- Kalshi: VERIFIED by official API documentation and OBSERVED. `GET /markets`
  supports `mve_filter=exclude|only`; MVE markets expose non-empty
  `mve_collection_ticker` and `mve_selected_legs`. The current client lacks the
  filter parameter and discovery does not exclude or label them.
- Polymarket US: OBSERVED. Market payloads expose `comboEnabled`, and event
  payloads expose `combos`; neither is currently used. The exact completeness of
  those flags across every market type remains UNKNOWN.

## Conclusion

Classification: **MIXED**, with directly supported `INGESTION_GAP`,
`NORMALIZATION_GAP`, and `COMBO_NOISE`. `UNIVERSE_OVERLAP_GAP` remains plausible
but is not established because the current discovery path discards authoritative
event/series/team signals before comparison. Some rule semantics remain a
`VENUE_METADATA_GAP`: detailed text is public, but several policies are not
consistently exposed as structured fields.

Highest-priority next milestone: enrich discovery records before matching by
joining each market to bounded, cached public parent-event metadata; preserve
authoritative event title/ID, category/league, event time, participant/team IDs,
and settlement-source identifiers; and exclude or separately classify structured
combo markets. Keep the `0.20` threshold, rankings, UNVERIFIED status, and manual
registry gate unchanged.
