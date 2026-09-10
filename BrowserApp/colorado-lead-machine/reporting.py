from __future__ import annotations

"""Workbook export helpers for the Colorado lead machine."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

if TYPE_CHECKING:
    from lead_machine import LeadMachine


def export_excel(machine: "LeadMachine", leads: list[dict]) -> Path:
    machine.log("Stage 5/5: Building Excel workbook")
    workbook = openpyxl.Workbook()
    leads_sheet = workbook.active
    leads_sheet.title = "Leads"

    header_fill = PatternFill("solid", start_color="1A3C5E")
    alt_fill = PatternFill("solid", start_color="EBF2FA")
    hot_fill = PatternFill("solid", start_color="FFD700")
    gold_fill = PatternFill("solid", start_color="FFF3CD")
    orange_fill = PatternFill("solid", start_color="FFE8CC")
    green_fill = PatternFill("solid", start_color="D6F4E3")
    white_fill = PatternFill("solid", start_color="FFFFFF")
    edit_fill = PatternFill("solid", start_color="EDF7F0")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    output_file = machine.config.save_path / f"colorado_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    columns = [
        "Seed Source",
        "Business Name",
        "City/Area",
        "Search Tile",
        "Opportunity Score",
        "Opportunity Label",
        "Lead Score",
        "Review Bucket",
        "Thriving Tier",
        "Thriving Score",
        "Revenue Tier",
        "Premium Fit Confidence",
        "Premium Fit Score",
        "Premium Fit Evidence",
        "Website Quality Score",
        "Website Grade",
        "Business Reality",
        "Reality Confidence",
        "Reality Details",
        "Opportunity Brief",
        "Opportunity Breakdown",
        "Why Kept",
        "Lead Rationale",
        "Score Breakdown",
        "Review Flags",
        "Phone",
        "Email",
        "Email Source",
        "Contact Cross-Reference",
        "Cross-Reference Details",
        "LinkedIn Profile",
        "Social Profiles",
        "Social Profile URLs",
        "Rating",
        "Reviews",
        "Review Velocity",
        "Formation Date",
        "Business Age Days",
        "Official Record Source",
        "Official Record State",
        "Official Record Status",
        "Official Status Category",
        "Official Match Type",
        "Official Match Confidence",
        "Official Status Note",
        "Official Latest Filing",
        "Official History Summary",
        "Official Entity ID",
        "Official Detail URL",
        "Colorado Record Status",
        "Colorado Status Category",
        "Colorado Match Type",
        "Colorado Match Confidence",
        "Colorado Status Note",
        "Colorado Latest Filing",
        "Colorado History Summary",
        "License Target",
        "License Status",
        "License Confidence",
        "License Details",
        "License Verify Link",
        "Business Type",
        "Address",
        "Website Status",
        "Web Presence Status",
        "Website Bucket",
        "Website Failure Type",
        "Web Presence Confidence",
        "Source Confidence Score",
        "Source Confidence Tier",
        "Website Assertion Status",
        "Sources Checked",
        "Source Confidence Matrix",
        "Source Confidence Warnings",
        "Why Surfaced",
        "Why Suppressed",
        "Evidence Freshness",
        "Next Best Action",
        "Audit Confidence",
        "Audit Confidence Score",
        "Last Audited At",
        "Last Verified At",
        "Data Freshness",
        "Primary Business Impact",
        "Best Pitch Angle",
        "Audit Issues",
        "Business Impact Summary",
        "Trigger Count",
        "Trigger Types",
        "Trigger Summary",
        "Trigger Details",
        "Trigger Version",
        "Last Triggered At",
        "Mobile Readiness",
        "SSL Status",
        "Page Speed Signal",
        "PageSpeed Status",
        "PageSpeed Strategy",
        "PageSpeed Performance Score",
        "PageSpeed Accessibility Score",
        "PageSpeed Best Practices Score",
        "PageSpeed SEO Score",
        "PageSpeed FCP",
        "PageSpeed LCP",
        "PageSpeed Speed Index",
        "PageSpeed TBT",
        "PageSpeed CLS",
        "PageSpeed CrUX Overall",
        "PageSpeed Field Summary",
        "PageSpeed Opportunities",
        "PageSpeed Error",
        "BuiltWith Status",
        "BuiltWith Domain",
        "BuiltWith First Indexed",
        "BuiltWith Last Indexed",
        "Tech Stack Signal",
        "Tech Stack Score",
        "Tech Stack Summary",
        "Tech Stack Weak Signals",
        "Tech Stack Strong Signals",
        "BuiltWith Groups",
        "BuiltWith Category Summary",
        "Tech Stack Error",
        "Contact Form Status",
        "Booking Flow Status",
        "CTA Strength",
        "SEO Basics",
        "Social Dependence",
        "Directory Dependence",
        "Image Quality Signal",
        "Navigation Quality",
        "Broken Link Count",
        "Broken Links",
        "Outdated Design Markers",
        "Website Quality Details",
        "Thriving Signals",
        "Revenue Note",
        "Web Presence Details",
        "Retry Recommended",
        "Retry Reason",
        "Discovery Sources Attempted",
        "Search Queries",
        "Search Providers",
        "Raw Result Count",
        "URLs Attempted",
        "HTTP Statuses",
        "Failure Reasons",
        "Verification Sources",
        "No Website Evidence",
        "Browser Fallback Used",
        "Browser Fallback Reason",
        "Browser Fallback Status",
        "Google Place ID",
        "Google Place URL",
        "Google Hours",
        "Google Price Level",
        "Google Photo Count",
        "Google Review Snippets",
        "Google Address Components",
        "Google Location",
        "Provider Evidence Summary",
        "DataForSEO Status",
        "DataForSEO Queries",
        "DataForSEO Owned Domains",
        "DataForSEO Result Count",
        "DataForSEO Failure Reason",
        "Yelp Match Status",
        "Yelp Match Confidence",
        "Yelp Business ID",
        "Yelp URL",
        "Yelp Rating",
        "Yelp Review Count",
        "Yelp Price",
        "Yelp Categories",
        "Yelp Phone",
        "Yelp Address",
        "Yelp Hours",
        "Yelp Photo Count",
        "Yelp Review Snippets",
        "Normalized Phone",
        "Normalized Address",
        "Business Identity Confidence",
        "Domain Checked",
        "Domain A Record",
        "Domain AAAA Record",
        "Domain MX/Address Record",
        "Domain SSL Present",
        "Domain SSL Expires",
        "Robots.txt Status",
        "Sitemap Status",
        "Domain RDAP Age Days",
        "Domain Verification Summary",
        "Social Bio Sources Checked",
        "Website Signals",
        "Official Website",
        "Listed On",
        "Contact Status",
        "Notes",
    ]
    widths = {
        "Seed Source": 16,
        "Business Name": 32,
        "City/Area": 20,
        "Search Tile": 12,
        "Lead Score": 12,
        "Review Bucket": 16,
        "Thriving Tier": 14,
        "Thriving Score": 14,
        "Revenue Tier": 20,
        "Premium Fit Confidence": 22,
        "Premium Fit Score": 16,
        "Premium Fit Evidence": 44,
        "Website Quality Score": 16,
        "Website Grade": 12,
        "Business Reality": 22,
        "Reality Confidence": 16,
        "Reality Details": 42,
        "Opportunity Brief": 52,
        "Why Kept": 52,
        "Lead Rationale": 42,
        "Score Breakdown": 44,
        "Review Flags": 28,
        "Phone": 18,
        "Email": 36,
        "Email Source": 22,
        "Contact Cross-Reference": 20,
        "Cross-Reference Details": 40,
        "LinkedIn Profile": 34,
        "Social Profiles": 40,
        "Social Profile URLs": 44,
        "Rating": 10,
        "Reviews": 10,
        "Formation Date": 16,
        "Business Age Days": 16,
        "Official Record Source": 26,
        "Official Record State": 14,
        "Official Record Status": 22,
        "Official Status Category": 18,
        "Official Match Type": 24,
        "Official Match Confidence": 18,
        "Official Status Note": 36,
        "Official Latest Filing": 30,
        "Official History Summary": 42,
        "Official Entity ID": 18,
        "Official Detail URL": 34,
        "Colorado Record Status": 22,
        "Colorado Status Category": 18,
        "Colorado Match Type": 24,
        "Colorado Match Confidence": 18,
        "Colorado Status Note": 34,
        "Colorado Latest Filing": 30,
        "Colorado History Summary": 42,
        "License Target": 20,
        "License Status": 24,
        "License Confidence": 18,
        "License Details": 42,
        "License Verify Link": 40,
        "Business Type": 26,
        "Address": 40,
        "Website Status": 22,
        "Web Presence Status": 20,
        "Website Bucket": 22,
        "Website Failure Type": 28,
        "Web Presence Confidence": 18,
        "Source Confidence Score": 18,
        "Source Confidence Tier": 18,
        "Website Assertion Status": 24,
        "Sources Checked": 36,
        "Source Confidence Matrix": 60,
        "Source Confidence Warnings": 42,
        "Why Surfaced": 46,
        "Why Suppressed": 46,
        "Evidence Freshness": 24,
        "Next Best Action": 36,
        "Audit Confidence": 16,
        "Audit Confidence Score": 18,
        "Last Audited At": 20,
        "Last Verified At": 20,
        "Data Freshness": 18,
        "Primary Business Impact": 40,
        "Best Pitch Angle": 42,
        "Audit Issues": 40,
        "Business Impact Summary": 44,
        "Trigger Count": 12,
        "Trigger Types": 28,
        "Trigger Summary": 48,
        "Trigger Details": 60,
        "Trigger Version": 14,
        "Last Triggered At": 20,
        "Mobile Readiness": 18,
        "SSL Status": 20,
        "Page Speed Signal": 18,
        "PageSpeed Status": 16,
        "PageSpeed Strategy": 14,
        "PageSpeed Performance Score": 18,
        "PageSpeed Accessibility Score": 18,
        "PageSpeed Best Practices Score": 18,
        "PageSpeed SEO Score": 18,
        "PageSpeed FCP": 14,
        "PageSpeed LCP": 14,
        "PageSpeed Speed Index": 16,
        "PageSpeed TBT": 14,
        "PageSpeed CLS": 14,
        "PageSpeed CrUX Overall": 18,
        "PageSpeed Field Summary": 42,
        "PageSpeed Opportunities": 48,
        "PageSpeed Error": 42,
        "BuiltWith Status": 18,
        "BuiltWith Domain": 24,
        "BuiltWith First Indexed": 18,
        "BuiltWith Last Indexed": 18,
        "Tech Stack Signal": 24,
        "Tech Stack Score": 16,
        "Tech Stack Summary": 46,
        "Tech Stack Weak Signals": 48,
        "Tech Stack Strong Signals": 44,
        "BuiltWith Groups": 60,
        "BuiltWith Category Summary": 60,
        "Tech Stack Error": 42,
        "Contact Form Status": 20,
        "Booking Flow Status": 22,
        "CTA Strength": 16,
        "SEO Basics": 18,
        "Social Dependence": 18,
        "Directory Dependence": 20,
        "Image Quality Signal": 20,
        "Navigation Quality": 20,
        "Broken Link Count": 14,
        "Broken Links": 34,
        "Outdated Design Markers": 28,
        "Website Quality Details": 38,
        "Thriving Signals": 44,
        "Revenue Note": 38,
        "Review Velocity": 16,
        "Web Presence Details": 34,
        "Retry Recommended": 14,
        "Retry Reason": 38,
        "Discovery Sources Attempted": 36,
        "Search Queries": 48,
        "Search Providers": 24,
        "Raw Result Count": 14,
        "URLs Attempted": 60,
        "HTTP Statuses": 22,
        "Failure Reasons": 48,
        "Verification Sources": 36,
        "No Website Evidence": 46,
        "Browser Fallback Used": 16,
        "Browser Fallback Reason": 34,
        "Browser Fallback Status": 24,
        "Google Place ID": 30,
        "Google Place URL": 42,
        "Google Hours": 42,
        "Google Price Level": 14,
        "Google Photo Count": 14,
        "Google Review Snippets": 56,
        "Google Address Components": 56,
        "Google Location": 26,
        "Provider Evidence Summary": 58,
        "DataForSEO Status": 20,
        "DataForSEO Queries": 48,
        "DataForSEO Owned Domains": 42,
        "DataForSEO Result Count": 16,
        "DataForSEO Failure Reason": 42,
        "Yelp Match Status": 18,
        "Yelp Match Confidence": 18,
        "Yelp Business ID": 24,
        "Yelp URL": 42,
        "Yelp Rating": 12,
        "Yelp Review Count": 14,
        "Yelp Price": 10,
        "Yelp Categories": 34,
        "Yelp Phone": 18,
        "Yelp Address": 40,
        "Yelp Hours": 46,
        "Yelp Photo Count": 14,
        "Yelp Review Snippets": 56,
        "Normalized Phone": 18,
        "Normalized Address": 42,
        "Business Identity Confidence": 18,
        "Domain Checked": 28,
        "Domain A Record": 14,
        "Domain AAAA Record": 14,
        "Domain MX/Address Record": 18,
        "Domain SSL Present": 14,
        "Domain SSL Expires": 24,
        "Robots.txt Status": 14,
        "Sitemap Status": 14,
        "Domain RDAP Age Days": 18,
        "Domain Verification Summary": 48,
        "Social Bio Sources Checked": 48,
        "Website Signals": 30,
        "Official Website": 34,
        "Listed On": 28,
        "Contact Status": 18,
        "Notes": 35,
    }

    for column_index, header in enumerate(columns, start=1):
        cell = leads_sheet.cell(1, column_index, header)
        cell.font = Font(bold=True, color="FFFFFF", name="Arial", size=11)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
        leads_sheet.column_dimensions[get_column_letter(column_index)].width = widths.get(header, 20)

    leads_sheet.row_dimensions[1].height = 32
    leads_sheet.freeze_panes = "A2"

    for row_index, lead in enumerate(leads, start=2):
        rating = lead.get("Rating") or 0
        has_email = bool(lead.get("Email"))
        web_presence = lead.get("Web Presence Status") or lead.get("Website Status")
        is_directory = web_presence in {"Directory only", "Social only"}
        is_broken = web_presence == "Broken site"
        is_weak = web_presence == "Weak site"
        is_unknown = web_presence == "Unknown web presence"

        review_bucket = str(lead.get("Review Bucket", ""))
        if review_bucket == "Hot lead":
            row_fill = hot_fill
        elif rating >= 4.8 and has_email:
            row_fill = gold_fill
        elif is_unknown or is_broken or is_weak:
            row_fill = orange_fill
        elif is_directory:
            row_fill = orange_fill
        elif has_email:
            row_fill = green_fill
        elif row_index % 2 == 0:
            row_fill = alt_fill
        else:
            row_fill = white_fill

        for column_index, key in enumerate(columns, start=1):
            cell = leads_sheet.cell(row_index, column_index, lead.get(key, ""))
            cell.font = Font(name="Arial", size=10)
            cell.border = border
            cell.alignment = Alignment(
                vertical="center",
                wrap_text=key in {
                    "Reality Details",
                    "Why Kept",
                    "Lead Rationale",
                    "Score Breakdown",
                    "Review Flags",
                    "Cross-Reference Details",
                    "License Details",
                    "Colorado Status Note",
                    "Colorado Latest Filing",
                    "Colorado History Summary",
                    "Web Presence Details",
                    "Retry Reason",
                    "Discovery Sources Attempted",
                    "Search Queries",
                    "URLs Attempted",
                    "Failure Reasons",
                    "Verification Sources",
                    "No Website Evidence",
                    "Sources Checked",
                    "Source Confidence Matrix",
                    "Source Confidence Warnings",
                    "Why Surfaced",
                    "Why Suppressed",
                    "Next Best Action",
                    "PageSpeed Field Summary",
                    "PageSpeed Opportunities",
                    "PageSpeed Error",
                    "Tech Stack Summary",
                    "Tech Stack Weak Signals",
                    "Tech Stack Strong Signals",
                    "BuiltWith Groups",
                    "BuiltWith Category Summary",
                    "Tech Stack Error",
                    "Browser Fallback Reason",
                    "Google Hours",
                    "Google Review Snippets",
                    "Google Address Components",
                    "Provider Evidence Summary",
                    "DataForSEO Queries",
                    "DataForSEO Owned Domains",
                    "DataForSEO Failure Reason",
                    "Yelp Address",
                    "Yelp Hours",
                    "Yelp Review Snippets",
                    "Domain Verification Summary",
                    "Social Bio Sources Checked",
                    "Website Signals",
                    "Social Profiles",
                    "Notes",
                },
            )
            cell.fill = edit_fill if key in {"Contact Status", "Notes"} else row_fill

    summary = workbook.create_sheet("Summary")
    summary["A1"] = "Colorado Lead Machine - Summary"
    summary["A1"].font = Font(bold=True, size=14, name="Arial", color="1A3C5E")

    total = len(leads)
    with_email = sum(1 for lead in leads if lead.get("Email"))
    phone_only = sum(1 for lead in leads if lead.get("Phone") and not lead.get("Email"))
    no_website = sum(1 for lead in leads if lead.get("Web Presence Status") == "No website")
    unknown_web_presence = sum(1 for lead in leads if lead.get("Web Presence Status") == "Unknown web presence")
    directory_only = sum(1 for lead in leads if lead.get("Web Presence Status") == "Directory only")
    social_only = sum(1 for lead in leads if lead.get("Web Presence Status") == "Social only")
    broken_site = sum(1 for lead in leads if lead.get("Web Presence Status") == "Broken site")
    weak_site = sum(1 for lead in leads if lead.get("Web Presence Status") == "Weak site")
    retry_recommended = sum(1 for lead in leads if str(lead.get("Retry Recommended", "")).strip().lower() == "yes")
    average_score = round(sum((lead.get("Lead Score") or 0) for lead in leads) / total, 1) if total else 0
    bucket_counts: dict[str, int] = {}
    for lead in leads:
        bucket = str(lead.get("Review Bucket", "")).strip() or "Unbucketed"
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    area_list = [area.strip() for area in machine.config.search_areas if area.strip()]
    if not area_list:
        region_label = "Colorado default areas"
    elif len(area_list) <= 3:
        region_label = ", ".join(area_list)
    else:
        region_label = f"{', '.join(area_list[:3])} + {len(area_list) - 3} more"

    stats = [
        ("", ""),
        ("Total Leads", total),
        ("With Email", with_email),
        ("Phone Only", phone_only),
        ("No Website Verified", no_website),
        ("Unknown Web Presence", unknown_web_presence),
        ("Retry Recommended", retry_recommended),
        ("Directory Listing Only", directory_only),
        ("Social Only", social_only),
        ("Broken Site", broken_site),
        ("Weak Site", weak_site),
        ("Average Lead Score", average_score),
        ("Generated", datetime.now().strftime("%B %d, %Y %I:%M %p")),
        ("Seed Mode", machine.config.seed_mode),
        ("Region", region_label),
        ("Min Business Age", f"{machine.config.min_business_age_days} days"),
        ("Min Rating", f"{machine.config.min_rating} stars with {machine.config.min_reviews}+ reviews"),
    ]

    for row_index, (label, value) in enumerate(stats, start=2):
        summary.cell(row_index, 1, label).font = Font(name="Arial", size=10, bold=bool(label))
        summary.cell(row_index, 2, value).font = Font(name="Arial", size=10)

    summary.cell(len(stats) + 3, 1, "Leads by City").font = Font(bold=True, name="Arial")
    city_counts: dict[str, int] = {}
    for lead in leads:
        city = lead.get("City/Area", "")
        city_counts[city] = city_counts.get(city, 0) + 1

    for row_index, (city, count) in enumerate(
        sorted(city_counts.items(), key=lambda item: -item[1]),
        start=len(stats) + 4,
    ):
        summary.cell(row_index, 1, city).font = Font(name="Arial", size=10)
        summary.cell(row_index, 2, count).font = Font(name="Arial", size=10)

    bucket_start = len(stats) + len(city_counts) + 6
    summary.cell(bucket_start, 1, "Review Buckets").font = Font(bold=True, name="Arial")
    for row_index, (bucket, count) in enumerate(
        sorted(bucket_counts.items(), key=lambda item: (-item[1], item[0])),
        start=bucket_start + 1,
    ):
        summary.cell(row_index, 1, bucket).font = Font(name="Arial", size=10)
        summary.cell(row_index, 2, count).font = Font(name="Arial", size=10)

    machine.record_stage_report(
        "export",
        "Build Excel workbook",
        actionable_leads=len(leads),
        workbook_path=str(output_file),
    )

    run_report_sheet = workbook.create_sheet("Run Report")
    run_report_sheet["A1"] = "Lead Machine - Run Report"
    run_report_sheet["A1"].font = Font(bold=True, size=12, name="Arial", color="1A3C5E")
    report_row = 3

    summary_items = {
        "Run ID": machine.current_run_id or "",
        "Status": machine.run_report.get("status", "completed"),
        "Seed Mode": machine.config.seed_mode,
        "Search Areas": ", ".join(area_list) if area_list else "Configured defaults",
        "Coverage Grid": machine.config.tile_grid_size,
        "Output Folder": str(machine.config.save_path),
    }
    run_report_sheet.cell(report_row, 1, "Run Summary").font = Font(bold=True, name="Arial")
    report_row += 1
    for label, value in summary_items.items():
        run_report_sheet.cell(report_row, 1, label).font = Font(name="Arial", size=10, bold=True)
        run_report_sheet.cell(report_row, 2, value).font = Font(name="Arial", size=10)
        report_row += 1

    report_row += 1
    for stage_key, stage_data in machine.run_report.get("stages", {}).items():
        run_report_sheet.cell(report_row, 1, stage_data.get("label", stage_key)).font = Font(
            bold=True, name="Arial", color="1A3C5E"
        )
        report_row += 1
        metrics = stage_data.get("metrics", {})
        for metric_name, value in metrics.items():
            run_report_sheet.cell(report_row, 1, str(metric_name).replace("_", " ").title()).font = Font(name="Arial", size=10)
            run_report_sheet.cell(report_row, 2, value).font = Font(name="Arial", size=10)
            report_row += 1
        report_row += 1

    legend = workbook.create_sheet("Color Legend")
    legend["A1"] = "Row Color Guide"
    legend["A1"].font = Font(bold=True, size=12, name="Arial", color="1A3C5E")
    legend_rows = [
        ("Gold", "FFF3CD", "4.8+ stars and has email"),
        ("Green", "D6F4E3", "Has email and is ready to contact"),
        ("Orange", "FFE8CC", "Unknown, directory, social-only, weak, or broken website lead"),
        ("Blue", "EBF2FA", "No website and no email yet"),
        ("White", "FFFFFF", "Standard lead"),
    ]
    for row_index, (name, color, desc) in enumerate(legend_rows, start=3):
        legend.cell(row_index, 1, name).fill = PatternFill("solid", start_color=color)
        legend.cell(row_index, 1, name).font = Font(name="Arial", size=10, bold=True)
        legend.cell(row_index, 1, name).border = border
        legend.cell(row_index, 2, desc).font = Font(name="Arial", size=10)

    legend.column_dimensions["A"].width = 12
    legend.column_dimensions["B"].width = 60
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 30
    run_report_sheet.column_dimensions["A"].width = 28
    run_report_sheet.column_dimensions["B"].width = 48

    workbook.save(output_file)
    machine.log(f"Excel file saved: {output_file}")
    return output_file
