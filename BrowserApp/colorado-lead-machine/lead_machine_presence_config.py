from __future__ import annotations

"""Static presence and domain-classification config for the Colorado lead machine."""

DIRECTORY_DOMAINS = {
    "yelp.com",
    "yellowpages.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tripadvisor.com",
    "bbb.org",
    "thumbtack.com",
    "angi.com",
    "homeadvisor.com",
    "houzz.com",
    "zillow.com",
    "realtor.com",
    "zocdoc.com",
    "healthgrades.com",
    "avvo.com",
    "findlaw.com",
    "opentable.com",
    "doordash.com",
    "grubhub.com",
    "ubereats.com",
    "styleseat.com",
    "booksy.com",
    "vagaro.com",
    "fresha.com",
}

DIRECTORY_LABELS = {
    "yelp.com": "Yelp listing",
    "yellowpages.com": "Yellow Pages listing",
    "facebook.com": "Facebook page only",
    "instagram.com": "Instagram only",
    "tripadvisor.com": "TripAdvisor listing",
    "thumbtack.com": "Thumbtack listing",
    "angi.com": "Angi listing",
    "homeadvisor.com": "HomeAdvisor listing",
    "houzz.com": "Houzz listing",
    "zillow.com": "Zillow listing",
    "realtor.com": "Realtor.com listing",
    "zocdoc.com": "ZocDoc listing",
    "healthgrades.com": "Healthgrades listing",
    "avvo.com": "Avvo listing",
    "findlaw.com": "FindLaw listing",
    "opentable.com": "OpenTable listing",
    "styleseat.com": "StyleSeat listing",
    "booksy.com": "Booksy listing",
    "vagaro.com": "Vagaro listing",
    "fresha.com": "Fresha listing",
}

SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "nextdoor.com",
    "alignable.com",
}

LINK_HUB_DOMAINS = {
    "linktr.ee",
    "linktree.com",
    "campsite.bio",
    "bio.link",
    "beacons.ai",
    "linkpop.com",
    "hoo.be",
    "stan.store",
    "tap.bio",
    "lnk.bio",
    "solo.to",
    "carrd.co",
    "milkshake.app",
    "direct.me",
    "bio.fm",
    "withkoji.com",
    "msha.ke",
    "snipfeed.co",
    "lynks.app",
}

MARKETPLACE_DOMAINS = {
    "etsy.com",
    "amazon.com",
    "ebay.com",
    "walmart.com",
    "myshopify.com",  # default Shopify subdomain = not an owned domain
    "squarespace.com",  # default subdomain only
    "square.site",  # default Square subdomain
    "wixsite.com",  # default Wix subdomain
    "weebly.com",  # default Weebly subdomain
    "godaddysites.com",  # default GoDaddy subdomain
}

PARKED_SITE_MARKERS = [
    "domain for sale",
    "buy this domain",
    "parked free",
    "this domain is parked",
    "default web site page",
]

# These markers are only checked against visible page text, not raw HTML,
# to avoid false positives from form placeholder attributes.
PARKED_TEXT_ONLY_MARKERS = [
    "coming soon",
    "under construction",
    "website coming soon",
]

TEMPLATE_BUILDER_MARKERS: dict[str, list[str]] = {
    "Wix free tier": [
        "wixsite.com",
        "x-wix-",
        "wix-warmup",
        "_wix_browser_sess",
        "wix-viewer-model",
    ],
    "GoDaddy builder": [
        "godaddysites.com",
        "img1.wsimg.com",
        "secureserver.net",
        "godaddy-dns",
    ],
    "Weebly": [
        ".weebly.com",
        "cdn2.editmysite.com",
        "weebly-footer",
    ],
    "Squarespace template": [
        "squarespace-cdn.com",
        "sqs-slide-container",
        "sqsp-",
    ],
    "Google Sites": [
        "sites.google.com",
        "googleusercontent.com/32s",
    ],
    "WordPress.com free": [
        ".wordpress.com",
        "wp.com/wp-content",
        "s0.wp.com",
    ],
}

JUNK_EMAIL_DOMAINS = {
    "example.com",
    "test.com",
    "domain.com",
    "yourdomain.com",
    "email.com",
    "wix.com",
    "squarespace.com",
    "wordpress.com",
    "shopify.com",
    "godaddy.com",
    "namecheap.com",
    "google.com",
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "yelp.com",
    "tripadvisor.com",
    "grubhub.com",
    "doordash.com",
}
