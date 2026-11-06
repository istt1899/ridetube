# Changelog

## App 0.3.12, service 0.3.12

- Fixes found by an independent review of the published 0.3.11: the daemon now sends the raw
  proxy URL over the child's stdin (a parsed object is accepted too), yt-dlp receives the URL
  string instead of the parsed dict, `proxy.js` takes `URL` from the `url` module (the head
  unit's Node 8 has no global `URL`), and `ytfetch.py check` drops the local imports that broke
  its proxy line (its direct-route lines become informational while a proxy is set).
- New host tests cover the full daemon -> stdin child -> proxy chain for CONNECT and SOCKS5,
  the Node 8 environment, yt-dlp's params and the check proxy line.

## App 0.3.11, service 0.3.11

- An admin-set HTTP/SOCKS5 proxy (`state/proxy.json`, 0600) carries all of the service's
  YouTube traffic (sign-in, InnerTube, SponsorBlock, thumbnails, yt-dlp and ranged audio),
  with DNS behind the proxy; the uplink preflight is skipped while a proxy is configured.
- New `proxy.js` tunnel module (CONNECT + SOCKS5, dependency-free) shared by `ytd.js` and
  `thumb.js`; `ytfetch.py` gains `--proxy-file`, a stdlib SOCKS5 client and a `proxy` line
  in `check`.
- Host tests: `test/test_proxy.js`, `test/test_proxy.py` (tunnels, auth failures, daemon
  plumbing, ranged GET through both protocols).

## App 0.3.7, service 0.3.8

- Video while driving takes effect only once switched on while the car is parked.
- The download stops when less than 256 MiB is left free on the head unit.
- README: data use, tested on, uninstall.

## App 0.3.6, service 0.3.7

First public release.
