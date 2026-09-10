"""Tests for Phase 1 presence resolution improvements.

Tests the new helpers (link hub, marketplace, social bio extraction)
and the updated discovery pipeline logic without hitting real networks.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import lead_machine as lead_machine_module
import lead_machine_search_config as search_config
from lead_machine import (
    LINK_HUB_DOMAINS,
    MARKETPLACE_DOMAINS,
    LeadMachine,
    LeadMachineConfig,
)


@pytest.fixture
def lm(tmp_path):
    """Create a LeadMachine with minimal config for unit testing."""
    config = LeadMachineConfig(
        google_maps_api_key="test-key",
        save_path=tmp_path,
    )
    machine = LeadMachine(config)
    return machine


class TestSearchLocations:
    def test_default_search_areas_remain_colorado(self):
        defaults = lead_machine_module.default_search_areas()

        assert "Denver, CO" in defaults
        assert "Los Angeles, CA" not in defaults

    def test_southern_california_area_resolves_from_static_preset(self, lm):
        lm.config.search_areas = ["Los Angeles, CA"]

        locations = lm.resolve_search_locations()

        assert locations == [{"name": "Los Angeles, CA", "lat": 34.0522, "lng": -118.2437}]

    def test_california_preset_covers_statewide_regions(self, lm):
        california = lead_machine_module.SEARCH_LOCATION_PRESETS["California"]
        california_names = [location["name"] for location in california]

        assert "Los Angeles, CA" in california_names
        assert "San Francisco, CA" in california_names
        assert "Sacramento, CA" in california_names
        assert len(california) > len(lead_machine_module.SEARCH_LOCATION_PRESETS["Southern California"])

    def test_orange_county_san_diego_preset_uses_normalized_requested_cities(self, lm):
        preset = lead_machine_module.SEARCH_LOCATION_PRESETS["Orange County / San Diego"]
        names = [location["name"] for location in preset]

        assert len(names) == 31
        assert "Newport Beach, CA" in names
        assert "Huntington Beach, CA" in names
        assert "Corona del Mar, CA" in names
        assert "San Juan Capistrano, CA" in names
        assert "Coronado, CA" in names
        assert "Encinitas, CA" in names
        assert "Imperial Beach, CA" in names
        assert search_config.SEARCH_AREA_PRESETS["Orange County / San Diego"] == names

    def test_orange_county_san_diego_locations_resolve_from_static_lookup(self, lm):
        lm.config.search_areas = ["Corona del Mar, CA", "Encinitas, CA", "Imperial Beach, CA"]

        with patch.object(lm, "geocode_search_area", side_effect=AssertionError("static location expected")):
            locations = lm.resolve_search_locations()

        assert [location["name"] for location in locations] == [
            "Corona del Mar, CA",
            "Encinitas, CA",
            "Imperial Beach, CA",
        ]

    def test_city_state_helpers_parse_california_context(self, lm):
        assert lm.city_from_area("Los Angeles, CA") == "Los Angeles"
        assert lm.state_code_from_area("Los Angeles, CA") == "CA"
        assert lm.state_name_from_area("Los Angeles, CA") == "California"
        assert lm.dataforseo_location_name("Los Angeles, CA") == "Los Angeles,California,United States"

    def test_premium_builders_profile_carries_client_fit_targeting(self):
        profile = search_config.SCAN_PROFILE_PRESETS["Premium builders"]

        assert profile["client_name"] == ""
        assert profile["target_profile_name"] == "Real estate and home building"
        assert profile["opportunity_focus"] == "any"
        assert profile["min_rating"] == 3.5
        assert profile["min_reviews"] == 3
        assert profile["min_business_age_days"] == 180
        assert "custom home builder" in profile["target_category_keywords"]
        assert "real estate developer" in profile["target_category_keywords"]
        assert "general_contractor" in profile["target_place_types"]


class TestNetworkHardening:
    def test_session_is_thread_local(self, lm):
        main_session = lm.session
        seen: dict[str, object] = {}

        def worker():
            seen["session"] = lm.session

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert seen["session"] is not main_session

    def test_fetch_page_keeps_tls_verification_enabled(self, lm):
        response = MagicMock(status_code=200, text="<html></html>", url="https://example.com", headers={})
        dns_answer = [(None, None, None, None, ("93.184.216.34", 0))]
        with patch("network.socket.getaddrinfo", return_value=dns_answer):
            with patch("requests.sessions.Session.request", return_value=response) as mock_request:
                html, resolved = lm.fetch_page("https://example.com")

        assert html == "<html></html>"
        assert resolved == "https://example.com"
        assert mock_request.call_args.kwargs["verify"] is True
        assert mock_request.call_args.kwargs["allow_redirects"] is False

    def test_fetch_page_rejects_localhost_url(self, lm):
        with patch("requests.sessions.Session.request") as mock_request:
            html, resolved = lm.fetch_page("http://127.0.0.1/admin")

        assert html is None
        assert resolved is None
        mock_request.assert_not_called()

    def test_fetch_page_rejects_non_http_scheme(self, lm):
        with patch("requests.sessions.Session.request") as mock_request:
            html, resolved = lm.fetch_page("file:///etc/passwd")

        assert html is None
        assert resolved is None
        mock_request.assert_not_called()

    def test_fetch_page_blocks_redirect_to_localhost(self, lm):
        redirect = MagicMock(
            status_code=302,
            headers={"Location": "http://127.0.0.1/admin"},
            is_redirect=True,
            url="https://example.com",
        )
        dns_answer = [(None, None, None, None, ("93.184.216.34", 0))]
        with patch("network.socket.getaddrinfo", return_value=dns_answer):
            with patch("requests.sessions.Session.request", return_value=redirect) as mock_request:
                html, resolved = lm.fetch_page("https://example.com")

        assert html is None
        assert resolved is None
        assert mock_request.call_count == 1

    def test_fetch_page_follows_safe_redirect_hop_by_hop(self, lm):
        redirect = MagicMock(
            status_code=302,
            headers={"Location": "https://www.example.com/home"},
            is_redirect=True,
            url="https://example.com",
        )
        final = MagicMock(
            status_code=200,
            text="<html>ok</html>",
            headers={},
            is_redirect=False,
            url="https://www.example.com/home",
        )
        dns_answer = [(None, None, None, None, ("93.184.216.34", 0))]
        with patch("network.socket.getaddrinfo", return_value=dns_answer):
            with patch("requests.sessions.Session.request", side_effect=[redirect, final]) as mock_request:
                html, resolved = lm.fetch_page("https://example.com")

        assert html == "<html>ok</html>"
        assert resolved == "https://www.example.com/home"
        assert mock_request.call_count == 2
        assert all(call.kwargs["allow_redirects"] is False for call in mock_request.call_args_list)


class TestProviderDiscovery:
    def test_dataforseo_discovers_likely_owned_domain(self, lm):
        lm.config.dataforseo_login = "login"
        lm.config.dataforseo_password = "password"
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "tasks": [
                {
                    "result": [
                        {
                            "items": [
                                {
                                    "type": "organic",
                                    "url": "https://joesplumbing.com",
                                    "title": "Joe's Plumbing",
                                    "description": "Official plumbing website",
                                },
                                {"type": "organic", "url": "https://www.yelp.com/biz/joes-plumbing"},
                            ]
                        }
                    ]
                }
            ]
        }

        with patch.object(lm, "_request", return_value=response) as request_mock:
            result = lm.dataforseo_serp_discovery("Joe's Plumbing", "Fort Collins, CO")

        assert result["enabled"] is True
        assert result["owned_urls"] == ["https://joesplumbing.com"]
        assert result["result_count"] == 4
        assert request_mock.call_count == 2
        payload = request_mock.call_args_list[0].kwargs["json"][0]
        assert payload["keyword"] == '"Joe\'s Plumbing" "Fort Collins, CO" official website'
        assert payload["location_name"] == "Fort Collins,Colorado,United States"

    def test_dataforseo_no_owned_domain_becomes_absence_evidence(self, lm):
        lm.config.dataforseo_login = "login"
        lm.config.dataforseo_password = "password"
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "tasks": [
                {
                    "result": [
                        {
                            "items": [
                                {"type": "organic", "url": "https://www.yelp.com/biz/joes-plumbing"},
                                {"type": "organic", "url": "https://facebook.com/joesplumbing"},
                            ]
                        }
                    ]
                }
            ]
        }

        with patch.object(lm, "_request", return_value=response):
            result = lm.dataforseo_serp_discovery("Joe's Plumbing", "Fort Collins, CO")

        assert result["owned_urls"] == []
        assert result["no_website_evidence"] == ["DataForSEO SERP search found no likely owned domain"]

    def test_dataforseo_uses_california_location_context(self, lm):
        lm.config.dataforseo_login = "login"
        lm.config.dataforseo_password = "password"
        response = MagicMock(status_code=200)
        response.json.return_value = {"tasks": [{"result": [{"items": []}]}]}

        with patch.object(lm, "_request", return_value=response) as request_mock:
            result = lm.dataforseo_serp_discovery("LA Plumbing", "Los Angeles, CA")

        assert result["enabled"] is True
        payload = request_mock.call_args_list[0].kwargs["json"][0]
        assert payload["keyword"] == '"LA Plumbing" "Los Angeles, CA" official website'
        assert payload["location_name"] == "Los Angeles,California,United States"

    def test_yelp_enrichment_sets_match_fields(self, lm):
        lm.config.yelp_api_key = "yelp-key"
        lead = {
            "Business Name": "Joe's Plumbing",
            "Address": "123 Main Street, Fort Collins, CO",
            "City/Area": "Fort Collins, CO",
            "Phone": "(970) 555-1212",
        }
        match_response = MagicMock(status_code=200)
        match_response.json.return_value = {
            "businesses": [
                {
                    "id": "joe-plumbing",
                    "name": "Joe's Plumbing",
                    "phone": "+19705551212",
                    "display_phone": "(970) 555-1212",
                    "rating": 4.7,
                    "review_count": 38,
                    "url": "https://www.yelp.com/biz/joe-plumbing",
                    "location": {"display_address": ["123 Main St", "Fort Collins, CO 80521"]},
                    "categories": [{"title": "Plumbing"}],
                }
            ]
        }
        details_response = MagicMock(status_code=200)
        details_response.json.return_value = {
            "id": "joe-plumbing",
            "price": "$$",
            "photos": ["https://photo.example/a.jpg"],
            "hours": [{"open": [{"day": 0, "start": "0800", "end": "1700"}]}],
        }
        reviews_response = MagicMock(status_code=200)
        reviews_response.json.return_value = {"reviews": [{"text": "Fast, professional, and local."}]}

        with patch.object(lm, "_request", side_effect=[match_response, details_response, reviews_response]):
            result = lm.yelp_enrich_lead(lead)

        assert result["Yelp Match Status"] == "Matched"
        assert result["Yelp Match Confidence"] >= 65
        assert result["Yelp Business ID"] == "joe-plumbing"
        assert result["Yelp Review Snippets"] == "Fast, professional, and local."

    def test_yelp_match_uses_state_from_city_area(self, lm):
        lm.config.yelp_api_key = "yelp-key"
        lead = {
            "Business Name": "LA Plumbing",
            "Address": "123 Main Street, Los Angeles, CA",
            "City/Area": "Los Angeles, CA",
            "Phone": "(213) 555-1212",
        }
        response = MagicMock(status_code=200)
        response.json.return_value = {"businesses": []}

        with patch.object(lm, "_request", return_value=response) as request_mock:
            result = lm.yelp_enrich_lead(lead)

        assert result["Yelp Match Status"] == "No match"
        params = request_mock.call_args.kwargs["params"]
        assert params["city"] == "Los Angeles"
        assert params["state"] == "CA"

    def test_domain_verification_records_dns_ssl_and_sitemap(self, lm):
        lm.config.enable_domain_checks = True
        lm.config.enable_rdap_checks = False

        def fake_fetch(url, timeout=5, provider=""):
            status = 200 if url.endswith("robots.txt") else 404
            return {"ok": status == 200, "status_code": status}

        with patch("discovery_providers.socket.getaddrinfo", return_value=[(socket.AF_INET, None, None, None, ("93.184.216.34", 443))]):
            with patch("discovery_providers._ssl_certificate_info", return_value=("Yes", "Jan 01 00:00:00 2030 GMT")):
                with patch.object(lm, "_has_mx_record", return_value=True):
                    with patch.object(lm, "fetch_page_result", side_effect=fake_fetch):
                        result = lm.verify_domain("https://joesplumbing.com")

        assert result["Domain Checked"] == "joesplumbing.com"
        assert result["Domain A Record"] == "Yes"
        assert result["Domain SSL Present"] == "Yes"
        assert result["Robots.txt Status"] == "200"
        assert result["Sitemap Status"] == "404"


class TestEmailValidationHardening:
    def test_stdlib_email_fallback_does_not_probe_port_25(self):
        lead_machine_module._mx_domain_cache.clear()
        with patch.object(lead_machine_module, "_dns_resolver", None):
            with patch.object(lead_machine_module.socket, "getaddrinfo", return_value=[("ok",)]) as mock_getaddrinfo:
                assert lead_machine_module._has_mx_record("example.org")

        assert mock_getaddrinfo.call_args.args[1] is None

    def test_clean_email_accepts_domain_with_a_record_when_dnspython_missing(self, lm):
        lead_machine_module._mx_domain_cache.clear()
        with patch.object(lead_machine_module, "_dns_resolver", None):
            with patch.object(lead_machine_module.socket, "getaddrinfo", return_value=[("ok",)]):
                assert lm.clean_email("owner@acme-valid.org") == "owner@acme-valid.org"


class TestContactEnrichmentStage:
    def test_hunter_domain_search_prefers_generic_valid_address(self, lm):
        lm.config.hunter_api_key = "hunter-key"
        lead = {
            "Business Name": "Acme Roofing",
            "Official Website": "https://www.acmeroofing.com",
        }
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "data": {
                "domain": "acmeroofing.com",
                "emails": [
                    {
                        "value": "owner@acmeroofing.com",
                        "type": "personal",
                        "confidence": 95,
                        "verification": {"status": "valid"},
                    },
                    {
                        "value": "info@acmeroofing.com",
                        "type": "generic",
                        "confidence": 72,
                        "verification": {"status": "valid"},
                    },
                ],
            }
        }

        with patch.object(lm, "_request", return_value=response) as request_mock:
            with patch.object(lm, "clean_email", side_effect=lambda value: value.lower()):
                email, source = lm.hunter_search_email(lead)

        assert email == "info@acmeroofing.com"
        assert source.startswith("Hunter Domain Search")
        params = request_mock.call_args.kwargs["params"]
        assert params["api_key"] == "hunter-key"
        assert params["domain"] == "acmeroofing.com"
        assert "company" not in params

    def test_find_email_stops_after_first_successful_hunter_source(self, lm):
        lead = {
            "Business Name": "Acme Roofing",
            "Address": "123 Main St, Denver, CO",
            "City/Area": "Denver, CO",
        }

        with patch.object(lm, "hunter_search_email", return_value=("owner@acme.com", "Hunter Domain Search")) as hunter_mock:
            with patch.object(lm, "scrape_known_site_email") as site_mock:
                with patch.object(lm, "guess_domain_email") as guess_mock:
                    email, source = lm.find_email(lead)

        assert email == "owner@acme.com"
        assert source == "Hunter Domain Search"
        hunter_mock.assert_called_once_with(lead)
        site_mock.assert_not_called()
        guess_mock.assert_not_called()

    def test_find_email_falls_back_to_guessed_source(self, lm):
        lead = {
            "Business Name": "Acme Roofing",
            "Address": "123 Main St, Denver, CO",
            "City/Area": "Denver, CO",
        }

        with patch("contact_enrichment.time.sleep"):
            with patch.object(lm, "hunter_search_email", return_value=(None, None)) as hunter_mock:
                with patch.object(lm, "scrape_known_site_email", return_value=(None, None)) as site_mock:
                    with patch.object(
                        lm,
                        "guess_domain_email",
                        return_value=("info@acmeroofing.com", "guessed (acmeroofing.com)"),
                    ) as guess_mock:
                        email, source = lm.find_email(lead)

        assert email == "info@acmeroofing.com"
        assert source == "Guessed - verify first"
        hunter_mock.assert_called_once_with(lead)
        site_mock.assert_called_once_with(lead)
        guess_mock.assert_called_once_with("Acme Roofing", "123 Main St, Denver, CO")

    def test_find_email_does_not_fetch_search_result_pages(self, lm):
        lead = {
            "Business Name": "Acme Roofing",
            "Address": "123 Main St, Denver, CO",
            "City/Area": "Denver, CO",
        }

        with patch("contact_enrichment.time.sleep"):
            with patch.object(lm, "hunter_search_email", return_value=(None, None)):
                with patch.object(lm, "scrape_known_site_email", return_value=(None, None)):
                    with patch.object(lm, "guess_domain_email", return_value=(None, None)):
                        with patch.object(lm, "fetch_page_result") as fetch_mock:
                            email, source = lm.find_email(lead)

        assert email is None
        assert source == "Not found"
        fetch_mock.assert_not_called()

    def test_enrich_with_emails_updates_leads_and_stage_report(self, lm):
        leads = [
            {"Business Name": "Acme Roofing", "Phone": "970-555-1234", "Email": ""},
            {"Business Name": "No Contact LLC", "Phone": "", "Email": ""},
        ]

        with patch("contact_enrichment.time.sleep"):
            with patch.object(
                lm,
                "find_email",
                side_effect=[("owner@acme.com", "DDG search"), (None, "Not found")],
            ) as find_email_mock:
                with patch.object(lm, "record_stage_report") as stage_report_mock:
                    updated = lm.enrich_with_emails(leads)

        assert updated[0]["Email"] == "owner@acme.com"
        assert updated[0]["Email Source"] == "DDG search"
        assert updated[1]["Email"] == ""
        assert updated[1]["Email Source"] == "Not found"
        assert find_email_mock.call_count == 2
        assert stage_report_mock.call_args.args == ("contact_enrichment", "Contact enrichment")
        assert stage_report_mock.call_args.kwargs["skipped"] is False
        assert stage_report_mock.call_args.kwargs["emails_found"] == 1
        assert stage_report_mock.call_args.kwargs["phone_only"] == 0
        assert stage_report_mock.call_args.kwargs["no_contact"] == 1
        assert stage_report_mock.call_args.kwargs["email_hit_rate_percent"] == 50

    def test_guess_domain_email_uses_safe_web_request(self, lm):
        response = MagicMock(status_code=200)
        with patch.object(lm, "_check_stop"):
            with patch.object(lm, "_safe_web_request", return_value=response) as safe_request_mock:
                guessed, source = lm.guess_domain_email("Acme Roofing", "Denver, CO")

        assert guessed is not None
        assert source is not None
        safe_request_mock.assert_called_once()
        assert safe_request_mock.call_args.args[:2] == ("head", "https://acmeroofing.com")


class TestMatchSafety:
    def test_colorado_entity_match_penalizes_token_collision(self, lm):
        row = {
            "entityname": "Colorado Plumbing Services LLC",
            "principalcity": "Denver",
        }
        score = lm.score_colorado_entity_match("Colorado Roofing and Plumbing", "Denver", row)
        assert score < 35

    def test_pick_best_colorado_entity_rejects_weak_partial_match(self, lm):
        row = {
            "entityname": "Colorado Plumbing Services LLC",
            "principalcity": "Denver",
        }
        best, score = lm.pick_best_colorado_entity("Colorado Roofing and Plumbing", "Denver", [row])
        assert best is None
        assert score < 35

    def test_google_match_score_penalizes_token_collision(self, lm):
        lead = {
            "Business Name": "Colorado Roofing and Plumbing",
            "City/Area": "Denver, CO",
            "Address": "123 Main St",
        }
        score = lm.google_match_score(lead, "Colorado Plumbing Services", "999 Other Ave, Denver, CO")
        assert score < 45

    def test_colorado_license_match_penalizes_token_collision(self, lm):
        row = {
            "entityname": "Colorado Plumbing Services",
            "city": "Denver",
            "licensestatusdescription": "Active",
        }
        score = lm.score_colorado_license_match("Colorado Roofing and Plumbing", "Denver", row)
        assert score < 35


class TestPlaceholderSafety:
    def test_coming_soon_on_real_site_not_flagged(self, lm):
        html = """<html><body>
        <h1>Spring service update</h1>
        <p>""" + " ".join(["our business is open and serving customers"] * 25) + """</p>
        <p>New location coming soon for summer jobs and more appointments.</p>
        <a href="/contact">Contact</a>
        <a href="/services">Services</a>
        </body></html>"""
        assert not lm.looks_parked_or_placeholder(html)

    def test_thin_coming_soon_page_flagged(self, lm):
        html = "<html><body><h1>Coming soon</h1><p>Under construction.</p></body></html>"
        assert lm.looks_parked_or_placeholder(html)


class TestColoradoQueryBuilder:
    def test_parse_formation_date_normalizes_zulu_timestamp(self, lm):
        parsed = lm.parse_formation_date("2024-01-02T03:04:05Z")
        assert parsed is not None
        assert parsed.tzinfo is None
        assert parsed.year == 2024

    def test_query_business_name_tokens_prefers_meaningful_words(self, lm):
        tokens = lm.query_business_name_tokens("Colorado Roofing and Plumbing Services")
        assert tokens[:2] == ["roofing", "plumbing"]

    def test_build_soql_like_clauses_sanitizes_tokens(self, lm):
        clauses = lm.build_soql_like_clauses(["entityname"], ["o'brien", "plumbing"], limit=2)
        assert clauses == [
            "upper(entityname) like '%OBRIEN%'",
            "upper(entityname) like '%PLUMBING%'",
        ]

    def test_build_soql_upper_equals_clause_normalizes_city(self, lm):
        clause = lm.build_soql_upper_equals_clause("principalcity", "Denver'); DROP")
        assert clause == "upper(principalcity) = 'DENVER DROP'"

    def test_build_soql_upper_equals_clause_rejects_unsafe_field_name(self, lm):
        with pytest.raises(ValueError):
            lm.build_soql_upper_equals_clause("principalcity) or 1=1 --", "Denver")

    def test_build_soql_like_clauses_rejects_unsafe_field_name(self, lm):
        with pytest.raises(ValueError):
            lm.build_soql_like_clauses(["entityname", "lastname) like '%X%' --"], ["plumbing"])


class TestCandidateFilteringStage:
    def test_secondary_dedup_prefers_higher_priority_same_address_and_phone(self, lm):
        candidates = [
            {
                "Business Name": "Example Plumbing",
                "Address": "123 Main St",
                "Phone": "970-555-1000",
                "Business Status": "OPERATIONAL",
                "Rating": 4.8,
                "Reviews": 25,
                "Seed Source": "Google Places",
                "Priority": 10,
            },
            {
                "Business Name": "Example Trades LLC",
                "Address": "123 Main St",
                "Phone": "970-555-1000",
                "Business Status": "OPERATIONAL",
                "Rating": 4.9,
                "Reviews": 30,
                "Seed Source": "Overture Maps",
                "Priority": 20,
            },
        ]

        with patch.object(lm, "_check_stop"):
            with patch.object(lm, "candidate_priority_score", side_effect=lambda lead: lead["Priority"]):
                with patch.object(lm, "sort_leads_by_priority", side_effect=lambda leads: list(leads)):
                    with patch.object(lm, "record_stage_report") as stage_report_mock:
                        filtered = lm.filter_candidate_leads(candidates)

        assert [lead["Business Name"] for lead in filtered] == ["Example Trades LLC"]
        assert stage_report_mock.call_args.args == ("filter", "Deduplicate and filter candidates")
        assert stage_report_mock.call_args.kwargs["kept"] == 1
        assert stage_report_mock.call_args.kwargs["duplicates_skipped"] == 1
        assert stage_report_mock.call_args.kwargs["address_phone_dupes"] == 1

    def test_unrated_google_candidate_is_skipped_but_unrated_overture_candidate_is_kept(self, lm):
        candidates = [
            {
                "Business Name": "Google Mystery Shop",
                "Address": "1 Main St",
                "Phone": "970-555-2000",
                "Business Status": "OPERATIONAL",
                "Rating": 0,
                "Reviews": 0,
                "Seed Source": "Google Places",
            },
            {
                "Business Name": "Overture Mystery Shop",
                "Address": "2 Main St",
                "Phone": "970-555-3000",
                "Business Status": "OPERATIONAL",
                "Rating": 0,
                "Reviews": 0,
                "Seed Source": "Overture Maps",
            },
        ]

        with patch.object(lm, "_check_stop"):
            with patch.object(lm, "sort_leads_by_priority", side_effect=lambda leads: list(leads)):
                with patch.object(lm, "record_stage_report") as stage_report_mock:
                    filtered = lm.filter_candidate_leads(candidates)

        assert [lead["Business Name"] for lead in filtered] == ["Overture Mystery Shop"]
        assert stage_report_mock.call_args.kwargs["kept"] == 1
        assert stage_report_mock.call_args.kwargs["low_rating_skipped"] == 1


class TestColoradoRecordsStage:
    def test_fetches_cslb_contractor_license_candidates(self, lm):
        initial = MagicMock(status_code=200)
        initial.text = """
            <input type="hidden" name="__VIEWSTATE" value="view" />
            <input type="hidden" name="__VIEWSTATEGENERATOR" value="gen" />
            <input type="hidden" name="__EVENTVALIDATION" value="event" />
        """
        results = MagicMock(status_code=200)
        results.text = """
            <a id="MainContent_dlMain_hlLicense_0" href="/OnlineServices/CheckLicenseII/LicenseDetail.aspx?LicNum=1105255">1105255</a>
            <span id="MainContent_dlMain_lblName_0">COASTAL CUSTOM HOMES INC</span>
            <span id="MainContent_dlMain_lblType_0">Name</span>
            <span id="MainContent_dlMain_lblCity_0">NEWPORT BEACH</span>
            <span id="MainContent_dlMain_lblLicenseStatus_0">Active</span>
        """

        with patch.object(lm, "_request", side_effect=[initial, results]) as request_mock:
            rows = lm.fetch_california_contractor_license_candidates("Coastal Custom Homes", "Newport Beach")

        assert rows == [
            {
                "business_name": "COASTAL CUSTOM HOMES INC",
                "name_type": "Name",
                "license_number": "1105255",
                "city": "NEWPORT BEACH",
                "license_status": "Active",
                "detail_url": "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/LicenseDetail.aspx?LicNum=1105255",
            }
        ]
        post_kwargs = request_mock.call_args_list[1].kwargs
        assert post_kwargs["data"]["ctl00$MainContent$NextName"] == "coastal custom homes"
        assert post_kwargs["data"]["__VIEWSTATE"] == "view"

    def test_california_contractor_license_verifies_active_match(self, lm):
        lead = {
            "Business Name": "Coastal Custom Homes",
            "Business Type": "custom home builder",
            "City/Area": "Newport Beach, CA",
        }
        rows = [
            {
                "business_name": "COASTAL CUSTOM HOMES INC",
                "license_number": "1105255",
                "city": "NEWPORT BEACH",
                "license_status": "Active",
                "detail_url": "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/LicenseDetail.aspx?LicNum=1105255",
            }
        ]

        with patch.object(lm, "fetch_california_contractor_license_candidates", return_value=rows):
            result = lm.validate_business_license(lead)

        assert result["target"] == "CSLB contractor"
        assert result["status"] == "License verified"
        assert result["confidence"] == "High"
        assert "Official CSLB license match" in result["details"]
        assert result["verify_url"].endswith("LicNum=1105255")

    def test_california_contractor_license_does_not_verify_city_mismatched_partial_match(self, lm):
        lead = {
            "Business Name": "Golden State Construction and Design Inc",
            "Business Type": "custom home builder",
            "City/Area": "Woodland Hills, CA",
        }
        rows = [
            {
                "business_name": "GOLDEN STATE CONSTRUCTION INC",
                "license_number": "611046",
                "city": "ORANGE",
                "license_status": "Active",
                "detail_url": "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/LicenseDetail.aspx?LicNum=611046",
            }
        ]

        with patch.object(lm, "fetch_california_contractor_license_candidates", return_value=rows):
            result = lm.validate_business_license(lead)

        assert result["target"] == "CSLB contractor"
        assert result["status"] == "Likely licensed - review"
        assert result["confidence"] == "Medium"

    def test_california_record_lookup_uses_calico_api(self, lm):
        lm.config.california_sos_api_key = "ca-key"
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "RecordCount": 1,
            "EntityData": [
                {
                    "EntityID": "202400012345",
                    "EntityName": "Golden State Plumbing LLC",
                    "FilingDate": "2021-06-15T10:30:00",
                    "StatusDescription": "Active",
                    "EntityCity": "LOS ANGELES",
                    "EntityState": "CA",
                }
            ],
        }

        with patch.object(lm, "_request", return_value=response) as request_mock:
            record = lm.lookup_california_business_record("Golden State Plumbing", "Los Angeles")

        assert record["match_found"] is True
        assert record["record_state"] == "CA"
        assert record["status_category"] == "Active"
        assert record["formation_date"] == "2021-06-15"
        assert record["entity_id"] == "202400012345"
        assert request_mock.call_args.kwargs["params"] == {"search-term": "golden state plumbing"}
        assert request_mock.call_args.kwargs["headers"] == {"Ocp-Apim-Subscription-Key": "ca-key"}

    def test_california_record_lookup_without_key_marks_not_configured(self, lm):
        record = lm.lookup_california_business_record("Golden State Plumbing", "Los Angeles")

        assert record["match_found"] is False
        assert record["record_state"] == "CA"
        assert record["match_type"] == "California records not configured"
        assert "CALICO API" in record["status_note"]

    def test_enriches_california_lead_with_official_record_fields(self, lm):
        lead = {
            "Business Name": "Golden State Plumbing",
            "City/Area": "Los Angeles, CA",
        }
        record = {
            "record_state": "CA",
            "source": "California Secretary of State",
            "match_found": True,
            "match_type": "Exact legal-name match",
            "match_confidence": "High",
            "formation_date": "2021-06-15",
            "age_days": 1850,
            "entity_id": "202400012345",
            "status": "Active",
            "status_category": "Active",
            "status_note": "Official California Secretary of State record is active",
            "latest_transaction": "Initial filing (2021-06-15)",
            "history_summary": "Initial filing (2021-06-15)",
            "detail_url": "https://bizfileonline.sos.ca.gov/search/business",
        }

        with patch.object(lm, "lookup_california_business_record", return_value=record):
            with patch.object(lm, "record_stage_report"):
                with patch.object(lm, "log"):
                    with patch.object(lm, "_check_stop"):
                        with patch.object(lm, "is_targeted_recheck", return_value=False):
                            kept = lm.enrich_with_colorado_records([lead])

        assert len(kept) == 1
        assert kept[0]["Official Record State"] == "CA"
        assert kept[0]["Official Status Category"] == "Active"
        assert kept[0]["Official Match Type"] == "Exact legal-name match"
        assert kept[0]["Formation Date"] == "2021-06-15"
        assert kept[0].get("Colorado Status Category", "") == ""

    def test_skips_likely_closed_business_when_not_targeted_recheck(self, lm):
        lead = {
            "Business Name": "Closed Shop",
            "City/Area": "Denver, CO",
        }
        record = {
            "match_found": True,
            "match_type": "Exact legal-name match",
            "match_confidence": "High",
            "formation_date": "2020-01-01",
            "age_days": 365,
            "entity_id": "12345",
            "status": "Dissolved",
            "status_category": "Likely closed",
            "status_note": "Official history shows dissolution",
            "latest_transaction": "Statement of dissolution",
            "history_summary": "Statement of dissolution (2024-01-01)",
        }

        with patch.object(lm, "lookup_colorado_business_record", return_value=record):
            with patch.object(lm, "record_stage_report"):
                with patch.object(lm, "log"):
                    with patch.object(lm, "_check_stop"):
                        with patch.object(lm, "is_targeted_recheck", return_value=False):
                            kept = lm.enrich_with_colorado_records([lead])

        assert kept == []
        assert lead["Colorado Status Category"] == "Likely closed"
        assert lead["Colorado Match Type"] == "Exact legal-name match"

    def test_retains_recent_business_for_targeted_recheck(self, lm):
        lead = {
            "Business Name": "New Shop",
            "City/Area": "Boulder, Colorado",
        }
        record = {
            "match_found": True,
            "match_type": "Exact legal-name match",
            "match_confidence": "High",
            "formation_date": "2026-04-01",
            "age_days": 10,
            "entity_id": "67890",
            "status": "Good Standing",
            "status_category": "Active",
            "status_note": "Official Colorado record is in good standing",
            "latest_transaction": "Statement filed",
            "history_summary": "Statement filed (2026-04-01)",
        }

        with patch.object(lm, "lookup_colorado_business_record", return_value=record):
            with patch.object(lm, "record_stage_report"):
                with patch.object(lm, "log"):
                    with patch.object(lm, "_check_stop"):
                        with patch.object(lm, "is_targeted_recheck", return_value=True):
                            kept = lm.enrich_with_colorado_records([lead])

        assert len(kept) == 1
        assert kept[0]["Business Age Days"] == 10
        assert kept[0]["Colorado Status Category"] == "Active"


# ── Link hub detection ───────────────────────────────

class TestLinkHubDetection:
    def test_linktree_detected(self, lm):
        assert lm.is_link_hub_url("https://linktr.ee/somebusiness")

    def test_campsite_bio_detected(self, lm):
        assert lm.is_link_hub_url("https://campsite.bio/mybiz")

    def test_beacons_detected(self, lm):
        assert lm.is_link_hub_url("https://beacons.ai/company")

    def test_normal_url_not_link_hub(self, lm):
        assert not lm.is_link_hub_url("https://example.com")

    def test_social_url_not_link_hub(self, lm):
        assert not lm.is_link_hub_url("https://facebook.com/page")


# ── Marketplace detection ────────────────────────────

class TestMarketplaceDetection:
    def test_etsy_detected(self, lm):
        assert lm.is_marketplace_url("https://www.etsy.com/shop/mybiz")

    def test_myshopify_detected(self, lm):
        assert lm.is_marketplace_url("https://mybiz.myshopify.com")

    def test_wixsite_detected(self, lm):
        assert lm.is_marketplace_url("https://mybiz.wixsite.com/site")

    def test_custom_domain_not_marketplace(self, lm):
        assert not lm.is_marketplace_url("https://mybusiness.com")

    def test_real_shopify_custom_domain_not_marketplace(self, lm):
        assert not lm.is_marketplace_url("https://shop.mybusiness.com")


# ── Business domain check ────────────────────────────

class TestLooksLikeBusinessDomain:
    def test_normal_domain(self, lm):
        assert lm._looks_like_business_domain("https://joesplumbing.com")

    def test_social_rejected(self, lm):
        assert not lm._looks_like_business_domain("https://facebook.com/joesplumbing")

    def test_google_rejected(self, lm):
        assert not lm._looks_like_business_domain("https://google.com")

    def test_youtube_rejected(self, lm):
        assert not lm._looks_like_business_domain("https://youtube.com/channel")

    def test_marketplace_rejected(self, lm):
        assert not lm._looks_like_business_domain("https://etsy.com/shop/x")

    def test_empty_rejected(self, lm):
        assert not lm._looks_like_business_domain("")


# ── Extract links from page ──────────────────────────

class TestExtractLinksFromPage:
    def test_extracts_outbound_links(self, lm):
        html = '''
        <html><body>
          <a href="https://example.com">Visit</a>
          <a href="https://facebook.com/biz">FB</a>
          <a href="/about">About</a>
          <a href="javascript:void(0)">JS</a>
        </body></html>
        '''
        links = lm.extract_links_from_page(html, "https://mysite.com")
        # Should get example.com and facebook.com, not /about (same domain) or javascript
        assert "https://example.com" in links
        assert "https://facebook.com/biz" in links
        assert len([l for l in links if "mysite.com" in l]) == 0

    def test_empty_html(self, lm):
        assert lm.extract_links_from_page("", "https://x.com") == []


# ── Follow link hub ──────────────────────────────────

class TestFollowLinkHub:
    def test_finds_business_link(self, lm):
        hub_html = '''
        <html><body>
          <a href="https://instagram.com/biz">Instagram</a>
          <a href="https://joesplumbing.com">My Website</a>
          <a href="https://facebook.com/biz">Facebook</a>
        </body></html>
        '''
        with patch.object(lm, "fetch_page", return_value=(hub_html, "https://linktr.ee/biz")):
            result = lm._follow_link_hub("https://linktr.ee/biz")
        assert result == "https://joesplumbing.com"

    def test_skips_social_and_marketplace(self, lm):
        hub_html = '''
        <html><body>
          <a href="https://instagram.com/biz">IG</a>
          <a href="https://etsy.com/shop/x">Etsy</a>
          <a href="https://yelp.com/biz/x">Yelp</a>
        </body></html>
        '''
        with patch.object(lm, "fetch_page", return_value=(hub_html, "https://linktr.ee/biz")):
            result = lm._follow_link_hub("https://linktr.ee/biz")
        assert result == ""

    def test_handles_fetch_failure(self, lm):
        with patch.object(lm, "fetch_page", return_value=(None, None)):
            result = lm._follow_link_hub("https://linktr.ee/biz")
        assert result == ""


# ── Social bio extraction ────────────────────────────

class TestSocialBioExtraction:
    def test_facebook_bio_website(self, lm):
        fb_html = '''
        <html><body>
          <a href="https://joesplumbing.com">Website</a>
          <a href="https://instagram.com/joes">IG</a>
        </body></html>
        '''
        with patch.object(lm, "fetch_page", return_value=(fb_html, "https://facebook.com/joes/about")):
            result = lm._extract_facebook_website("https://facebook.com/joes")
        assert result == "https://joesplumbing.com"

    def test_facebook_bio_linktree_followed(self, lm):
        fb_html = '<html><body><a href="https://linktr.ee/joes">Links</a></body></html>'
        hub_html = '<html><body><a href="https://joesplumbing.com">Site</a></body></html>'

        def mock_fetch(url, timeout=8):
            if "facebook" in url:
                return (fb_html, url)
            if "linktr.ee" in url:
                return (hub_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            result = lm._extract_facebook_website("https://facebook.com/joes")
        assert result == "https://joesplumbing.com"

    def test_instagram_bio_link_hub(self, lm):
        ig_html = '<html><body><a href="https://linktr.ee/biz">Link in bio</a></body></html>'
        hub_html = '<html><body><a href="https://mybiz.com">Website</a></body></html>'

        def mock_fetch(url, timeout=8):
            if "instagram" in url:
                return (ig_html, url)
            if "linktr.ee" in url:
                return (hub_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            result = lm._extract_instagram_website("https://instagram.com/biz")
        assert result == "https://mybiz.com"

    def test_linkedin_website_extraction(self, lm):
        li_html = '<html><body><a href="https://acmecorp.com">Company Website</a></body></html>'
        with patch.object(lm, "fetch_page", return_value=(li_html, "https://linkedin.com/company/acme")):
            result = lm._extract_linkedin_website("https://linkedin.com/company/acme")
        assert result == "https://acmecorp.com"

    def test_social_bio_no_website(self, lm):
        html = '<html><body><a href="https://facebook.com/other">Other</a></body></html>'
        with patch.object(lm, "fetch_page", return_value=(html, "https://facebook.com/biz/about")):
            result = lm._extract_facebook_website("https://facebook.com/biz")
        assert result == ""

    def test_extract_website_dispatches_by_platform(self, lm):
        with patch.object(lm, "_extract_facebook_website", return_value="https://fb-result.com") as mock_fb:
            result = lm.extract_website_from_social_bio("https://facebook.com/biz")
        assert result == "https://fb-result.com"
        mock_fb.assert_called_once()

    def test_extract_website_handles_exception(self, lm):
        with patch.object(lm, "_extract_facebook_website", side_effect=Exception("fail")):
            result = lm.extract_website_from_social_bio("https://facebook.com/biz")
        assert result == ""


# ── classify_known_web_presence additions ────────────

class TestClassifyWebPresenceAdditions:
    def test_marketplace_url_classified(self, lm):
        result = lm.classify_known_web_presence("https://mybiz.myshopify.com")
        assert result[0] == "Directory only"
        assert "marketplace" in result[2].lower() or "platform" in result[2].lower()

    def test_link_hub_url_followed(self, lm):
        hub_html = '<html><body><a href="https://realbiz.com">Website</a></body></html>'
        # Mock fetch_page for the link hub, then mock _fetch_with_fallbacks for realbiz.com
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://realbiz.com"
        mock_response.text = "<html><head><title>Real Biz</title><meta name='viewport' content='width=device-width'></head><body><p>Content here with enough words to pass quality checks and avoid being flagged as thin content by the inspection engine.</p><a href='/contact'>Contact</a><a href='/about'>About</a><a href='/services'>Services</a><a href='/team'>Team</a><a href='/blog'>Blog</a><img src='1.jpg'><img src='2.jpg'><img src='3.jpg'></body></html>"
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.history = []

        def mock_fetch(url, timeout=8):
            if "linktr.ee" in url:
                return (hub_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_fetch_with_fallbacks", return_value=(mock_response, "https://realbiz.com", False)):
                result = lm.classify_known_web_presence("https://linktr.ee/mybiz")
        # Should have followed the link hub and classified the real site
        assert result[0] not in {"No website", "Social only"}
        assert "realbiz.com" in result[1]

    def test_link_hub_no_website_found(self, lm):
        hub_html = '<html><body><a href="https://instagram.com/x">IG</a></body></html>'
        with patch.object(lm, "fetch_page", return_value=(hub_html, "https://linktr.ee/x")):
            result = lm.classify_known_web_presence("https://linktr.ee/x")
        assert result[0] == "Social only"
        assert "link" in result[2].lower()


# ── choose_web_presence_result ───────────────────────

class TestChooseWebPresenceResult:
    def test_real_website_beats_social(self, lm):
        social = lm.make_web_result("Social only", "https://fb.com/x", "FB", "High", "fb")
        real = lm.make_web_result("Real website", "https://biz.com", "Site", "High", "ok")
        assert lm.choose_web_presence_result(social, real)[0] == "Real website"

    def test_basic_site_beats_broken(self, lm):
        broken = lm.make_web_result("Broken site", "https://x.com", "Broken", "High", "err")
        basic = lm.make_web_result("Basic site", "https://biz.com", "Basic", "High", "ok")
        assert lm.choose_web_presence_result(broken, basic)[0] == "Basic site"

    def test_weak_site_beats_social(self, lm):
        social = lm.make_web_result("Social only", "https://fb.com/x", "FB", "High", "fb")
        weak = lm.make_web_result("Weak site", "https://biz.com", "Weak", "Medium", "issues")
        assert lm.choose_web_presence_result(social, weak)[0] == "Weak site"

    def test_higher_confidence_wins_tie(self, lm):
        low = lm.make_web_result("Broken site", "https://x.com", "Broken", "Low", "err")
        high = lm.make_web_result("Broken site", "https://y.com", "Broken", "High", "err2")
        result = lm.choose_web_presence_result(low, high)
        assert result[3] == "High"

    def test_empty_results_returns_unknown_web_presence(self, lm):
        result = lm.choose_web_presence_result()
        assert result[0] == "Unknown web presence"


# ── discover_presence_bundle (mocked) ────────────────

class TestDiscoverPresenceBundle:
    def test_returns_discovery_sources(self, lm):
        search_html = '<html><body><a href="https://joesplumbing.com">Link</a></body></html>'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://joesplumbing.com"
        mock_response.text = "<html><head><title>Joe's Plumbing</title><meta name='viewport' content='width=device-width'></head><body><p>We are a plumbing company serving Colorado.</p><a href='/contact'>Contact</a><a href='/about'>About</a><a href='/services'>Services</a><a href='/faq'>FAQ</a><a href='/blog'>Blog</a><img src='a.jpg'><img src='b.jpg'><img src='c.jpg'><form><input></form></body></html>"
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.3
        mock_response.history = []

        def mock_fetch_result(url, timeout=10, provider="", query=""):
            if "duckduckgo" in url:
                return {
                    "ok": True,
                    "url": url,
                    "final_url": url,
                    "status_code": 200,
                    "html": search_html,
                    "provider": provider,
                    "query": query,
                    "attempted_urls": [url],
                    "http_statuses": [200],
                    "retry_recommended": False,
                }
            return {
                "ok": False,
                "url": url,
                "final_url": url,
                "status_code": 0,
                "html": "",
                "error_type": "mock_miss",
                "error_message": "mock miss",
                "provider": provider,
                "query": query,
                "attempted_urls": [url],
                "http_statuses": [],
                "retry_recommended": True,
            }

        with patch.object(lm, "fetch_page_result", side_effect=mock_fetch_result):
            with patch.object(lm, "_fetch_with_fallbacks", return_value=(mock_response, "https://joesplumbing.com", False)):
                with patch.object(lm, "discover_public_profiles", return_value=("", [], "No LinkedIn or social profiles found")):
                    bundle = lm.discover_presence_bundle("Joe's Plumbing", "Fort Collins")

        assert "discovery_sources" in bundle
        assert len(bundle["discovery_sources"]) > 0
        assert bundle["web_result"][0] not in {"No website", "Social only"}

    def test_social_bio_checked_when_no_website(self, lm):
        """When search only finds social profiles, bio links should be checked."""
        search_html = '<html><body><a href="https://facebook.com/joesplumbing">FB</a></body></html>'

        fb_about_html = '<html><body><a href="https://joesplumbing.com">Website</a></body></html>'

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://joesplumbing.com"
        mock_response.text = "<html><head><title>Joe's Plumbing</title></head><body><p>Colorado plumber</p></body></html>"
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.3
        mock_response.history = []

        call_count = {"n": 0}

        def mock_fetch(url, timeout=10):
            call_count["n"] += 1
            if "duckduckgo" in url:
                return (search_html, url)
            if "facebook.com" in url:
                return (fb_about_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_fetch_with_fallbacks", return_value=(mock_response, "https://joesplumbing.com", False)):
                with patch.object(lm, "discover_public_profiles", return_value=("", ["https://facebook.com/joesplumbing"], "Social profiles: 1")):
                    with patch.object(lm, "_check_stop", return_value=None):
                        bundle = lm.discover_presence_bundle("Joe's Plumbing", "Fort Collins")

        # Should have found the website via Facebook bio
        assert bundle["web_result"][0] not in {"No website", "Social only", "Directory only"}
        # Discovery sources should mention social bio
        assert any("social bio" in s for s in bundle["discovery_sources"])

    def test_social_bio_checks_more_than_one_profile(self, lm):
        search_html = "<html><body>No useful links</body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://joesplumbing.com"
        mock_response.text = "<html><head><title>Joe's Plumbing</title><meta name='viewport' content='width=device-width'></head><body><p>Colorado plumber</p><a href='/contact'>Contact</a><a href='/about'>About</a><a href='/services'>Services</a><a href='/faq'>FAQ</a><a href='/blog'>Blog</a><img src='a.jpg'><img src='b.jpg'><img src='c.jpg'><form><input></form></body></html>"
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.3
        mock_response.history = []

        def mock_fetch_result(url, timeout=10, provider="", query=""):
            return {
                "ok": True,
                "url": url,
                "final_url": url,
                "status_code": 200,
                "html": search_html,
                "provider": provider,
                "query": query,
                "attempted_urls": [url],
                "http_statuses": [200],
                "retry_recommended": False,
            }

        with patch.object(lm, "fetch_page_result", side_effect=mock_fetch_result):
            with patch.object(lm, "dataforseo_serp_discovery", return_value={"enabled": False}):
                with patch.object(
                    lm,
                    "discover_public_profiles",
                    return_value=(
                        "",
                        ["https://facebook.com/joesplumbing", "https://instagram.com/joesplumbing"],
                        "Social profiles: 2",
                    ),
                ):
                    with patch.object(lm, "extract_website_from_social_bio", side_effect=["", "https://joesplumbing.com"]):
                        with patch.object(lm, "_fetch_with_fallbacks", return_value=(mock_response, "https://joesplumbing.com", False)):
                            bundle = lm.discover_presence_bundle("Joe's Plumbing", "Fort Collins")

        assert bundle["web_result"][0] not in {"No website", "Unknown web presence", "Social only"}
        assert bundle["social_bio_sources_checked"] == [
            "https://facebook.com/joesplumbing",
            "https://instagram.com/joesplumbing",
        ]


class TestVerifyWebPresence:
    def test_filters_real_website_when_focus_requires_web_gap(self, lm):
        lm.config.opportunity_focus = "broken_site"
        lead = {
            "Business Name": "Joe's Plumbing",
            "Seed Website": "https://joesplumbing.com",
            "Official Website": "",
            "City/Area": "Fort Collins, CO",
            "Listed On": "",
            "Website Status": "Website listed",
        }
        real_site = lm.make_web_result(
            "Real website",
            "https://joesplumbing.com",
            "Standalone website responded successfully",
            "High",
            "live site",
        )

        with patch.object(lm, "classify_known_web_presence", return_value=real_site):
            with patch.object(lm, "apply_website_opportunity_audit", return_value={}):
                with patch.object(lm, "record_stage_report"):
                    with patch.object(lm, "log"):
                        with patch.object(lm, "_check_stop"):
                            with patch.object(lm, "is_targeted_recheck", return_value=False):
                                kept = lm.verify_web_presence([lead])

        assert kept == []

    def test_keeps_real_website_for_premium_client_fit_focus(self, lm):
        lm.config.opportunity_focus = "premium_client_fit"
        lead = {
            "Business Name": "Joe's Plumbing",
            "Seed Website": "https://joesplumbing.com",
            "Official Website": "",
            "City/Area": "Fort Collins, CO",
            "Listed On": "",
            "Website Status": "Website listed",
        }
        real_site = lm.make_web_result(
            "Real website",
            "https://joesplumbing.com",
            "Standalone website responded successfully",
            "High",
            "live site",
        )

        with patch.object(lm, "classify_known_web_presence", return_value=real_site):
            with patch.object(lm, "apply_website_opportunity_audit", return_value={}):
                with patch.object(lm, "record_stage_report"):
                    with patch.object(lm, "log"):
                        with patch.object(lm, "_check_stop"):
                            with patch.object(lm, "is_targeted_recheck", return_value=False):
                                kept = lm.verify_web_presence([lead])

        assert len(kept) == 1
        assert kept[0]["Web Presence Status"] == "Real website"

    def test_keeps_real_website_for_any_opportunity_focus(self, lm):
        lm.config.opportunity_focus = "any"
        lead = {
            "Business Name": "Joe's Plumbing",
            "Seed Website": "https://joesplumbing.com",
            "Official Website": "",
            "City/Area": "Fort Collins, CO",
            "Listed On": "",
            "Website Status": "Website listed",
        }
        real_site = lm.make_web_result(
            "Real website",
            "https://joesplumbing.com",
            "Standalone website responded successfully",
            "High",
            "live site",
        )

        with patch.object(lm, "classify_known_web_presence", return_value=real_site):
            with patch.object(lm, "apply_website_opportunity_audit", return_value={}):
                with patch.object(lm, "record_stage_report"):
                    with patch.object(lm, "log"):
                        with patch.object(lm, "_check_stop"):
                            with patch.object(lm, "is_targeted_recheck", return_value=False):
                                kept = lm.verify_web_presence([lead])

        assert len(kept) == 1
        assert kept[0]["Web Presence Status"] == "Real website"

    def test_keeps_social_only_lead_and_populates_discovery_metadata(self, lm):
        lead = {
            "Business Name": "Joe's Plumbing",
            "Seed Website": "",
            "Official Website": "",
            "City/Area": "Fort Collins, CO",
            "Listed On": "",
            "Website Status": "",
        }
        social_only = lm.make_web_result(
            "Social only",
            "https://instagram.com/joesplumbing",
            "Only social-media pages were found",
            "High",
            "instagram.com",
        )
        bundle = {
            "web_result": social_only,
            "linkedin_url": "https://linkedin.com/company/joesplumbing",
            "social_profiles": ["https://instagram.com/joesplumbing"],
            "discovery_sources": ["search: profile discovery"],
        }

        with patch.object(lm, "discover_presence_bundle", return_value=bundle):
            with patch.object(lm, "apply_website_opportunity_audit", return_value={}):
                with patch.object(lm, "record_stage_report"):
                    with patch.object(lm, "log"):
                        with patch.object(lm, "_check_stop"):
                            with patch.object(lm, "is_targeted_recheck", return_value=False):
                                kept = lm.verify_web_presence([lead])

        assert len(kept) == 1
        assert kept[0]["Web Presence Status"] == "Social only"
        assert kept[0]["LinkedIn Profile"] == "https://linkedin.com/company/joesplumbing"
        assert kept[0]["Social Profile URLs"] == "https://instagram.com/joesplumbing"
        assert kept[0]["Discovery Sources"] == "search: profile discovery"
        assert kept[0]["Listed On"] == "Only social-media pages were found"


# ── Quality scoring (penalty-from-max) ──────────────

class TestQualityScoring:
    """Test the penalty-from-max scoring model in inspect_site_quality."""

    def _make_good_html(self):
        """HTML that should score Established (>=80, plenty of visible words)."""
        return '''<html><head>
            <title>Joe's Plumbing - Fort Collins Colorado</title>
            <meta name="viewport" content="width=device-width">
        </head><body>
            <nav><a href="/about">About</a><a href="/services">Services</a>
            <a href="/contact">Contact</a><a href="/gallery">Gallery</a>
            <a href="/blog">Blog</a><a href="/faq">FAQ</a></nav>
            <p>''' + ' '.join(['quality plumbing service'] * 130) + '''</p>
            <p>Call us: 970-555-1234 | info@joesplumbing.com</p>
            <form><input type="text"><button>Get Quote</button></form>
            <img src="1.jpg"><img src="2.jpg"><img src="3.jpg"><img src="4.jpg">
            <a href="https://facebook.com/joes">FB</a>
            <a href="https://instagram.com/joes">IG</a>
            <a href="https://twitter.com/joes">TW</a>
        </body></html>'''

    def _make_weak_html(self):
        """HTML that should score Weak."""
        return '''<html><head><title>Home</title></head><body>
            <p>Welcome to our site.</p>
        </body></html>'''

    def _make_basic_html(self):
        """HTML that should score Basic — has some things, missing others."""
        return '''<html><head>
            <title>Joe's Plumbing Company</title>
            <meta name="viewport" content="width=device-width">
        </head><body>
            <nav><a href="/about">About</a><a href="/services">Services</a></nav>
            <p>''' + ' '.join(['we do plumbing work'] * 60) + '''</p>
            <p>Call us: 970-555-1234</p>
            <img src="1.jpg">
        </body></html>'''

    def test_good_site_scores_established(self, lm):
        with patch.object(lm, "_fetch_inner_page_evidence", return_value={
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }):
            quality, details, _, evidence = lm.inspect_site_quality(
                self._make_good_html(), "https://joesplumbing.com",
                http_status=200, fetch_time_ms=300,
            )
        assert quality == "Established"
        assert evidence["Quality Score"] >= 80

    def test_weak_site_scores_weak(self, lm):
        with patch.object(lm, "_fetch_inner_page_evidence", return_value={
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }):
            quality, details, _, evidence = lm.inspect_site_quality(
                self._make_weak_html(), "https://bad-site.com",
                http_status=200, fetch_time_ms=300,
            )
        assert quality == "Weak"
        assert evidence["Quality Score"] < 50

    def test_basic_site_scores_basic(self, lm):
        with patch.object(lm, "_fetch_inner_page_evidence", return_value={
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }):
            quality, details, _, evidence = lm.inspect_site_quality(
                self._make_basic_html(), "https://ok-site.com",
                http_status=200, fetch_time_ms=300,
            )
        assert quality == "Basic"
        assert 50 <= evidence["Quality Score"] < 80

    def test_score_clamped_to_0_100(self, lm):
        """Even the worst site shouldn't go below 0."""
        minimal_html = "<html><body></body></html>"
        with patch.object(lm, "_fetch_inner_page_evidence", return_value={
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }):
            _, _, _, evidence = lm.inspect_site_quality(
                minimal_html, "https://empty.com",
                http_status=200, fetch_time_ms=300,
            )
        assert 0 <= evidence["Quality Score"] <= 100

    def test_inner_page_bonuses_boost_score(self, lm):
        """Contact form + services page should push score up."""
        html = self._make_basic_html()
        no_inner = {
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }
        with_inner = {
            "Inner Pages Checked": 2, "Inner Page URLs": "/contact, /services",
            "Total Word Count": 200, "Contact Page Found": "Yes",
            "Contact Page Has Form": "Yes", "Services Described": "Yes",
            "About Page Found": "",
        }

        with patch.object(lm, "_fetch_inner_page_evidence", return_value=no_inner):
            _, _, _, ev_without = lm.inspect_site_quality(
                html, "https://ok-site.com", http_status=200, fetch_time_ms=300,
            )
        with patch.object(lm, "_fetch_inner_page_evidence", return_value=with_inner):
            _, _, _, ev_with = lm.inspect_site_quality(
                html, "https://ok-site.com", http_status=200, fetch_time_ms=300,
            )
        assert ev_with["Quality Score"] > ev_without["Quality Score"]

    def test_quality_score_stored_in_evidence(self, lm):
        with patch.object(lm, "_fetch_inner_page_evidence", return_value={
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }):
            _, _, _, evidence = lm.inspect_site_quality(
                self._make_good_html(), "https://biz.com",
                http_status=200, fetch_time_ms=300,
            )
        assert "Quality Score" in evidence
        assert isinstance(evidence["Quality Score"], int)

    def test_text_word_count_strips_noscript_and_hidden(self, lm):
        """Wix templates inflate word count via noscript/hidden divs.
        Verify those are stripped so visible content is what counts."""
        html = '''<html><body>
            <h1>Welcome</h1>
            <p>Book today.</p>
            <noscript>Please enable javascript to view this site properly with all features and content available for the best experience</noscript>
            <div style="display:none">Hidden SEO content with many many many words that user cannot see</div>
            <div aria-hidden="true">Aria hidden boilerplate also lots of words here</div>
            <div hidden>Other hidden boilerplate text words words words</div>
        </body></html>'''
        # Visible: "Welcome Book today" → 3 words (today is 5 chars including period)
        assert lm.text_word_count(html) <= 5

    def test_bonus_budget_capped(self, lm):
        """A site with every possible bonus signal cannot vault past the cap.
        Wix templates ship with analytics, schema, booking, review widget,
        social, contact form, and services for free — bonuses must not stack
        unbounded."""
        thin_html = '''<html><head>
            <title>Thin Site With Generic Title</title>
            <meta name="viewport" content="width=device-width">
        </head><body>
            <nav><a href="/a">A</a><a href="/b">B</a><a href="/c">C</a>
            <a href="/d">D</a><a href="/e">E</a><a href="/f">F</a></nav>
            <p>Welcome.</p>
            <p>Phone: 970-555-1234</p>
            <form><button>Book</button></form>
            <img src="1.jpg"><img src="2.jpg"><img src="3.jpg">
        </body></html>'''
        loaded_inner = {
            "Inner Pages Checked": 2, "Inner Page URLs": "/contact, /services",
            "Total Word Count": 50, "Contact Page Found": "Yes",
            "Contact Page Has Form": "Yes", "Services Described": "Yes",
            "About Page Found": "Yes",
        }
        with patch.object(lm, "_fetch_inner_page_evidence", return_value=loaded_inner):
            with patch.object(lm, "extract_site_evidence", wraps=lm.extract_site_evidence) as wrapped:
                _, _, _, evidence = lm.inspect_site_quality(
                    thin_html, "https://thin-but-loaded.com",
                    http_status=200, fetch_time_ms=300,
                )
        # Thin word count means hard cap kicks in.
        assert evidence["Quality Score"] <= 70

    def test_thin_content_cannot_reach_established(self, lm):
        """No matter how many features a page has, fewer than 200 visible
        words should hold the score below Established."""
        html = '''<html><head>
            <title>Real Looking Title For The Page</title>
            <meta name="viewport" content="width=device-width">
        </head><body>
            <nav><a href="/a">A</a><a href="/b">B</a><a href="/c">C</a>
            <a href="/d">D</a><a href="/e">E</a><a href="/f">F</a></nav>
            <p>Short page. Phone 970-555-1234. Email a@b.com. Get a quote.</p>
            <form><button>Book</button></form>
            <img src="1.jpg"><img src="2.jpg"><img src="3.jpg"><img src="4.jpg">
        </body></html>'''
        with patch.object(lm, "_fetch_inner_page_evidence", return_value={
            "Inner Pages Checked": 0, "Inner Page URLs": "",
            "Total Word Count": 0, "Contact Page Found": "",
            "Contact Page Has Form": "", "Services Described": "",
            "About Page Found": "",
        }):
            quality, _, _, evidence = lm.inspect_site_quality(
                html, "https://thin.com", http_status=200, fetch_time_ms=300,
            )
        assert evidence["Quality Score"] < 80
        assert quality != "Established"


# ── Confidence scoring (numeric 0-100) ──────────────

class TestAuditConfidenceScore:
    """Test compute_audit_confidence_score from website_audit module."""

    def test_no_evidence_low_score(self):
        from website_audit import compute_audit_confidence_score
        score = compute_audit_confidence_score(
            "Low", "Broken site", evidence_available=False,
        )
        assert score < 35

    def test_full_evidence_high_score(self):
        from website_audit import compute_audit_confidence_score
        score = compute_audit_confidence_score(
            "High", "Real website", evidence_available=True,
            page_title="Joe's Plumbing", meta_description="Best plumber",
            word_count=400, form_count_checked=True, image_count_checked=True,
            internal_link_count_checked=True, viewport_meta="Found",
            on_page_phones="970-555-1234", on_page_emails="info@biz.com",
            cta_terms="get a quote", http_status="200",
            inner_pages_checked=2, discovery_source_count=3,
        )
        assert score >= 65

    def test_no_website_with_multiple_sources(self):
        from website_audit import compute_audit_confidence_score
        score = compute_audit_confidence_score(
            "High", "No website", evidence_available=False,
            discovery_source_count=3,
        )
        assert score >= 50

    def test_inner_pages_boost_score(self):
        from website_audit import compute_audit_confidence_score
        base = compute_audit_confidence_score(
            "Medium", "Real website", evidence_available=True,
            page_title="Site", word_count=200,
            form_count_checked=True, image_count_checked=True,
            internal_link_count_checked=True, viewport_meta="Found",
            inner_pages_checked=0,
        )
        boosted = compute_audit_confidence_score(
            "Medium", "Real website", evidence_available=True,
            page_title="Site", word_count=200,
            form_count_checked=True, image_count_checked=True,
            internal_link_count_checked=True, viewport_meta="Found",
            inner_pages_checked=2,
        )
        assert boosted > base

    def test_score_clamped_to_0_100(self):
        from website_audit import compute_audit_confidence_score
        score = compute_audit_confidence_score(
            "High", "Real website", evidence_available=True,
            page_title="Joe", meta_description="Best",
            word_count=500, form_count_checked=True, image_count_checked=True,
            internal_link_count_checked=True, viewport_meta="Found",
            on_page_phones="x", on_page_emails="y", cta_terms="z",
            http_status="200", inner_pages_checked=5,
            discovery_source_count=10,
        )
        assert 0 <= score <= 100


class TestConfidenceLabelFromScore:
    def test_high_label(self):
        from website_audit import confidence_label_from_score
        assert confidence_label_from_score(80) == "High"
        assert confidence_label_from_score(65) == "High"

    def test_medium_label(self):
        from website_audit import confidence_label_from_score
        assert confidence_label_from_score(50) == "Medium"
        assert confidence_label_from_score(35) == "Medium"

    def test_low_label(self):
        from website_audit import confidence_label_from_score
        assert confidence_label_from_score(20) == "Low"
        assert confidence_label_from_score(0) == "Low"


# ── Opportunity score + suppressors ─────────────────

class TestOpportunityFocus:
    def _premium_lead(self, **overrides):
        lead = {
            "Web Presence Status": "Real website",
            "Reviews": 125,
            "Revenue Tier": "Medium-high revenue",
            "Thriving Tier": "Established",
            "Business Reality": "Real active business",
            "Opportunity Label": "Moderate opportunity",
            "Opportunity Score": 16,
            "Website Quality Score": 58,
            "PageSpeed Performance Score": 62,
            "CTA Terms": "",
            "Booking Terms": "",
            "Form Count": 0,
            "On-Page Phones": "970-555-1234",
            "On-Page Emails": "",
            "Broken Link Count": 0,
            "Outdated Design Markers": "",
            "Phone": "970-555-1234",
            "Email": "",
        }
        lead.update(overrides)
        return lead

    def test_premium_client_fit_keeps_budget_fit_real_site_with_gap(self, lm):
        lm.config.opportunity_focus = "premium_client_fit"

        assert lm.lead_matches_opportunity_focus(self._premium_lead())

    def test_premium_client_fit_keeps_low_review_high_value_builder(self, lm):
        lm.config.opportunity_focus = "premium_client_fit"
        lm.config.min_reviews = 3
        lead = self._premium_lead(
            **{
                "Business Name": "Coastal Custom Home Builders",
                "Business Type": "custom home builder",
                "Reviews": 3,
                "Revenue Tier": "Low/unknown revenue",
                "Thriving Tier": "Early-stage",
            }
        )

        assert lm.lead_matches_opportunity_focus(lead)

    def test_premium_client_fit_rejects_strong_site_even_with_reviews(self, lm):
        lm.config.opportunity_focus = "premium_client_fit"
        lead = self._premium_lead(
            **{
                "Opportunity Label": "Low opportunity despite high quality",
                "Opportunity Score": 0,
                "Website Quality Score": 86,
                "PageSpeed Performance Score": 92,
                "CTA Terms": "request a consultation",
                "Booking Terms": "schedule",
                "Form Count": 2,
            }
        )

        assert not lm.lead_matches_opportunity_focus(lead)

    def test_premium_client_fit_rejects_low_budget_real_site(self, lm):
        lm.config.opportunity_focus = "premium_client_fit"
        lead = self._premium_lead(
            **{
                "Reviews": 8,
                "Revenue Tier": "Low/unknown revenue",
                "Thriving Tier": "Early-stage",
            }
        )

        assert not lm.lead_matches_opportunity_focus(lead)


class TestOpportunityScore:
    def _base_lead(self, **overrides):
        lead = {
            "Web Presence Status": "No website",
            "Website Quality Score": 0,
            "Website Grade": "F",
            "Quality Score": 0,
            "CTA Terms": "",
            "Booking Terms": "",
            "Form Count": 0,
            "On-Page Phones": "",
            "On-Page Emails": "",
            "Viewport Meta": "",
            "Word Count": 0,
            "Outdated Design Markers": "",
            "Thriving Tier": "",
            "SSL Status": "",
            "Resolved Website URL": "",
            "Internal Link Count": 0,
            "Image Count": 0,
            "Page Title": "",
            "Meta Description": "",
            "Google Analytics": "",
            "Facebook Pixel": "",
            "Booking Platforms": "None detected",
            "Contact Page Has Form": "",
            "Services Described": "",
        }
        lead.update(overrides)
        return lead

    def test_no_website_high_opp(self, lm):
        lead = self._base_lead()
        result = lm.compute_opportunity_score(lead, 50)
        assert result["opportunity_score"] >= 40
        assert "High" in result["opportunity_label"] or "Good" in result["opportunity_label"]

    def test_broken_site_high_opp(self, lm):
        lead = self._base_lead(
            **{"Web Presence Status": "Broken site", "Website Quality Score": 8}
        )
        result = lm.compute_opportunity_score(lead, 50)
        assert result["opportunity_score"] >= 35

    def test_established_site_gets_disqualified(self, lm):
        """A strong site with many signals should be disqualified."""
        lead = self._base_lead(**{
            "Web Presence Status": "Real website",
            "Website Quality Score": 80,
            "Website Grade": "A",
            "Quality Score": 85,
            "SSL Status": "HTTPS Valid",
            "Viewport Meta": "Found",
            "CTA Terms": "get a quote",
            "Booking Terms": "schedule",
            "Form Count": 2,
            "On-Page Phones": "970-555-1234",
            "On-Page Emails": "info@biz.com",
            "Internal Link Count": 12,
            "Image Count": 8,
            "Word Count": 500,
            "Page Title": "Joe's Plumbing - Fort Collins",
            "Meta Description": "Best plumber in town",
            "Google Analytics": "Detected",
            "Booking Platforms": "Calendly",
            "Contact Page Has Form": "Yes",
            "Services Described": "Yes",
        })
        result = lm.compute_opportunity_score(lead, 50)
        assert result["opportunity_label"] == "Low opportunity despite high quality"

    def test_weak_site_not_suppressed(self, lm):
        """A weak site should NOT get suppressed."""
        lead = self._base_lead(**{
            "Web Presence Status": "Weak site",
            "Website Quality Score": 25,
            "Quality Score": 25,
        })
        result = lm.compute_opportunity_score(lead, 50)
        assert "despite high quality" not in result["opportunity_label"]
        assert result["opportunity_score"] >= 20

    def test_thriving_no_website_bonus(self, lm):
        lead = self._base_lead(**{"Thriving Tier": "Thriving"})
        result = lm.compute_opportunity_score(lead, 50)
        assert result["opportunity_score"] >= 50

    def test_basic_site_moderate_quality_suppressed(self, lm):
        """A basic site with decent signals should get suppressed."""
        lead = self._base_lead(**{
            "Web Presence Status": "Basic site",
            "Website Quality Score": 55,
            "Website Grade": "B",
            "Quality Score": 55,
            "SSL Status": "HTTPS Valid",
            "Viewport Meta": "Found",
            "CTA Terms": "contact us",
            "Form Count": 1,
            "On-Page Phones": "970-555-1234",
            "Internal Link Count": 6,
            "Image Count": 4,
            "Word Count": 200,
            "Page Title": "Local Business Site",
            "Meta Description": "We serve Colorado",
        })
        result = lm.compute_opportunity_score(lead, 40)
        # Should be suppressed or low
        assert result["opportunity_score"] < 20 or "suppressor" in result["opportunity_breakdown"].lower()


class TestReviewBuckets:
    def _base_lead(self, **overrides):
        lead = {
            "Web Presence Status": "No website",
            "Website Quality Score": 0,
            "Quality Score": 0,
            "Phone": "970-555-1234",
            "Email": "",
            "Business Reality": "Confirmed match",
            "Thriving Tier": "Established",
            "Opportunity Score": 50,
            "Opportunity Label": "High opportunity",
        }
        lead.update(overrides)
        return lead

    def test_no_contact_bucketed(self, lm):
        lead = self._base_lead(Phone="", Email="")
        bucket = lm.choose_review_bucket(lead, 60, [])
        assert bucket == "No contact"

    def test_hot_lead(self, lm):
        lead = self._base_lead(**{
            "Opportunity Score": 50,
            "Thriving Tier": "Thriving",
        })
        bucket = lm.choose_review_bucket(lead, 70, [])
        assert bucket == "Hot lead"

    def test_low_quality_suppresses(self, lm):
        lead = self._base_lead(**{
            "Opportunity Label": "Low opportunity despite high quality",
        })
        bucket = lm.choose_review_bucket(lead, 60, [])
        assert bucket == "Low priority"

    def test_decent_site_low_priority(self, lm):
        lead = self._base_lead(**{
            "Web Presence Status": "Basic site",
            "Website Quality Score": 55,
            "Quality Score": 55,
            "Opportunity Score": 15,
        })
        bucket = lm.choose_review_bucket(lead, 35, [])
        assert bucket == "Low priority"


# ── Inner page URL discovery ────────────────────────

class TestDiscoverInnerPageUrls:
    def test_finds_contact_page(self, lm):
        html = '<html><body><nav><a href="/contact">Contact Us</a></nav></body></html>'
        urls = lm._discover_inner_page_urls(html, "https://biz.com")
        assert "contact" in urls
        assert urls["contact"] == "https://biz.com/contact"

    def test_finds_about_page(self, lm):
        html = '<html><body><nav><a href="/about-us">About Us</a></nav></body></html>'
        urls = lm._discover_inner_page_urls(html, "https://biz.com")
        assert "about" in urls

    def test_finds_services_page(self, lm):
        html = '<html><body><nav><a href="/services">Our Services</a></nav></body></html>'
        urls = lm._discover_inner_page_urls(html, "https://biz.com")
        assert "services" in urls

    def test_finds_multiple_page_types(self, lm):
        html = '''<html><body><nav>
            <a href="/contact">Contact</a>
            <a href="/about">About</a>
            <a href="/services">Services</a>
        </nav></body></html>'''
        urls = lm._discover_inner_page_urls(html, "https://biz.com")
        assert len(urls) == 3

    def test_caps_at_three(self, lm):
        html = '''<html><body><nav>
            <a href="/contact">Contact</a>
            <a href="/about">About</a>
            <a href="/services">Services</a>
            <a href="/products">Products</a>
        </nav></body></html>'''
        urls = lm._discover_inner_page_urls(html, "https://biz.com")
        assert len(urls) <= 3

    def test_ignores_external_links(self, lm):
        html = '<html><body><a href="https://facebook.com/contact">Contact on FB</a></body></html>'
        urls = lm._discover_inner_page_urls(html, "https://biz.com")
        assert len(urls) == 0

    def test_empty_html(self, lm):
        urls = lm._discover_inner_page_urls("", "https://biz.com")
        assert urls == {}

    def test_resolves_relative_urls(self, lm):
        html = '<html><body><a href="contact-us">Contact</a></body></html>'
        urls = lm._discover_inner_page_urls(html, "https://biz.com/")
        if "contact" in urls:
            assert urls["contact"].startswith("https://biz.com")


# ── Inner page evidence fetching ────────────────────

class TestFetchInnerPageEvidence:
    def test_fetches_contact_page_with_form(self, lm):
        homepage = '<html><body><nav><a href="/contact">Contact</a></nav></body></html>'
        contact_html = '<html><body><h1>Contact Us</h1><form><input type="text"><button>Send</button></form></body></html>'

        def mock_fetch(url, timeout=8):
            if "/contact" in url:
                return (contact_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_check_stop", return_value=None):
                result = lm._fetch_inner_page_evidence("https://biz.com", homepage)

        assert result["Contact Page Found"] == "Yes"
        assert result["Contact Page Has Form"] == "Yes"
        assert result["Inner Pages Checked"] >= 1

    def test_fetches_services_page(self, lm):
        homepage = '<html><body><nav><a href="/services">Services</a></nav></body></html>'
        services_html = '<html><body>' + ' '.join(['word'] * 60) + '</body></html>'

        def mock_fetch(url, timeout=8):
            if "/services" in url:
                return (services_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_check_stop", return_value=None):
                result = lm._fetch_inner_page_evidence("https://biz.com", homepage)

        assert result["Services Described"] == "Yes"

    def test_thin_services_page(self, lm):
        homepage = '<html><body><nav><a href="/services">Services</a></nav></body></html>'
        services_html = '<html><body>We do stuff.</body></html>'

        def mock_fetch(url, timeout=8):
            if "/services" in url:
                return (services_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_check_stop", return_value=None):
                result = lm._fetch_inner_page_evidence("https://biz.com", homepage)

        assert result["Services Described"] == "Thin"

    def test_about_page_detected(self, lm):
        homepage = '<html><body><nav><a href="/about">About Us</a></nav></body></html>'
        about_html = '<html><body><h1>About Our Company</h1><p>We have been around since 2010.</p></body></html>'

        def mock_fetch(url, timeout=8):
            if "/about" in url:
                return (about_html, url)
            return (None, None)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_check_stop", return_value=None):
                result = lm._fetch_inner_page_evidence("https://biz.com", homepage)

        assert result["About Page Found"] == "Yes"

    def test_no_inner_pages_found(self, lm):
        homepage = '<html><body><p>Just text, no nav.</p></body></html>'
        result = lm._fetch_inner_page_evidence("https://biz.com", homepage)
        assert result["Inner Pages Checked"] == 0
        assert result["Contact Page Found"] == ""

    def test_fetch_failure_handled(self, lm):
        homepage = '<html><body><nav><a href="/contact">Contact</a></nav></body></html>'

        with patch.object(lm, "fetch_page", return_value=(None, None)):
            with patch.object(lm, "_check_stop", return_value=None):
                result = lm._fetch_inner_page_evidence("https://biz.com", homepage)

        assert result["Inner Pages Checked"] == 0
        assert result["Contact Page Found"] == ""

    def test_max_two_pages_fetched(self, lm):
        homepage = '''<html><body><nav>
            <a href="/contact">Contact</a>
            <a href="/services">Services</a>
            <a href="/about">About</a>
        </nav></body></html>'''
        page_html = '<html><body><form><input></form><p>' + ' '.join(['word'] * 60) + '</p></body></html>'
        fetch_count = {"n": 0}

        def mock_fetch(url, timeout=8):
            fetch_count["n"] += 1
            return (page_html, url)

        with patch.object(lm, "fetch_page", side_effect=mock_fetch):
            with patch.object(lm, "_check_stop", return_value=None):
                result = lm._fetch_inner_page_evidence("https://biz.com", homepage)

        assert fetch_count["n"] <= 2
        assert result["Inner Pages Checked"] <= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
