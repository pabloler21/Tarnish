# Deploying the landing page

One static file (`docs/index.html`) served by Caddy on a Vultr VPS, under a DuckDNS subdomain.
No build step, no CI, no secrets: the VPS clones the public repo and Caddy serves `docs/` from it.

## 1. DuckDNS — once

Register a subdomain at [duckdns.org](https://www.duckdns.org/) and set its IP to the VPS's.

The VPS has a **static** IP, so skip the update cron every DuckDNS guide tells you to install —
that exists for home connections whose IP moves. Setting the record once is the whole job.

## 2. Open the ports

In the Vultr firewall, allow **80 and 443**. Port 80 is not optional: Let's Encrypt's HTTP
challenge lands there, and closing it after the first certificate breaks renewal ~60 days later,
silently, on a page nobody is watching.

## 3. On the VPS — once

```bash
# Caddy, from the official repo (the distro package lags)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# the site
sudo git clone https://github.com/pabloler21/Tarnish /srv/tarnish
sudo cp /srv/tarnish/deploy/Caddyfile /etc/caddy/Caddyfile
# edit the hostname in /etc/caddy/Caddyfile to your DuckDNS subdomain first
sudo systemctl reload caddy
```

The Caddy package installs and enables its own systemd unit, so there is nothing else to write.
HTTPS is automatic — no certbot, no renewal cron.

## 4. Updating the page

```bash
sudo git -C /srv/tarnish pull
```

Caddy reads from disk per request, so there is no reload and no restart. That is the whole
deployment.

## Checks when it does not work

```bash
sudo systemctl status caddy          # is it running
sudo journalctl -u caddy -n 50       # ACME failures show up here in full
dig +short tarnish.duckdns.org       # does the name resolve to this box yet
```

A certificate failure is almost always one of three things: the DNS record has not propagated,
port 80 is closed, or something else already owns port 80.

## A note on DuckDNS

DuckDNS is free and volunteer-run, and it went down on 2026-06-21. That is fine for a demo URL and
a bad bet for the product's permanent address — when the name is settled (`Tarnish` is still a
working codename), move to a domain you own. Changing it is one line in the Caddyfile plus a DNS
record; Caddy re-issues the certificate on its own.
