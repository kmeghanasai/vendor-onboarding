"""Generate clearly fictional text-based PDFs for the PS2 demo scenarios."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "pdf" / "demo_documents"
LEGACY_FILES = (
    "name_mismatch_gst.pdf",
    "name_mismatch_bank.pdf",
    "gstin_mismatch_gst.pdf",
    "gstin_mismatch_bank.pdf",
)


def create_pdf(filename: str, title: str, scenario: str, fields: list[tuple[str, str]]) -> None:
    path = OUTPUT_DIR / filename
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=24 * mm,
        leftMargin=24 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title=f"Synthetic demo - {title}",
        author="Vendor onboarding demo generator",
    )
    styles = getSampleStyleSheet()
    banner = ParagraphStyle(
        "Banner",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#9B1C1C"),
        alignment=1,
        spaceAfter=8,
    )
    cell = ParagraphStyle("Cell", parent=styles["BodyText"], fontSize=9, leading=12)
    label = ParagraphStyle("Label", parent=cell, fontName="Helvetica-Bold")
    story = [
        Paragraph("SYNTHETIC DEMO SAMPLE - NOT A REAL DOCUMENT", banner),
        Paragraph(title, styles["Title"]),
        Paragraph(f"Scenario: {scenario}", styles["Heading3"]),
        Spacer(1, 10 * mm),
    ]
    rows = [[Paragraph("Field", label), Paragraph("Synthetic value", label)]]
    rows.extend([[Paragraph(name, label), Paragraph(value, cell)] for name, value in fields])
    table = Table(rows, colWidths=[55 * mm, 90 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9CA3AF")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.extend([
        table,
        Spacer(1, 15 * mm),
        Paragraph(
            "For software demonstration only. The organization, contact details, account numbers, "
            "and document are fictional and must not be used for any real transaction or verification.",
            styles["BodyText"],
        ),
    ])
    document.build(story)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename in LEGACY_FILES:
        legacy_path = OUTPUT_DIR / filename
        if legacy_path.exists():
            legacy_path.unlink()

    scenarios = [
        {
            "prefix": "happy_path",
            "scenario": "Matching happy path",
            "legal_name": "Acme Demo Technologies Private Limited",
            "gstin": "27AAPFU0939F1ZV",
            "beneficiary_name": "Acme Demo Technologies Private Limited",
            "account_number": "001234567890",
            "ifsc": "HDFC0001234",
        },
        {
            "prefix": "sole_proprietor_name",
            "scenario": "Trade name differs from proprietor legal name",
            "legal_name": "Meghana Sai",
            "gstin": "27AAPFU0939F1ZV",
            "beneficiary_name": "Meghana Sai",
            "account_number": "001234567890",
            "ifsc": "HDFC0001234",
        },
        {
            "prefix": "mixed_identity",
            "scenario": "GST evidence belongs to a different legal entity",
            "legal_name": "Northwind Demo Logistics Private Limited",
            "gstin": "27ABCDE1234F1Z0",
            "beneficiary_name": "Acme Demo Technologies Private Limited",
            "account_number": "001234567890",
            "ifsc": "HDFC0001234",
        },
        {
            "prefix": "bank_change",
            "scenario": "Previously approved GSTIN submitted with new bank details",
            "legal_name": "Acme Demo Technologies Private Limited",
            "gstin": "27AAPFU0939F1ZV",
            "beneficiary_name": "Acme Demo Technologies Private Limited",
            "account_number": "009999888877",
            "ifsc": "ICIC0005678",
        },
        {
            "prefix": "shared_account",
            "scenario": "Bank account was previously approved for another GSTIN",
            "legal_name": "Bluebird Demo Services Private Limited",
            "gstin": "07ABCDE1234F1Z2",
            "beneficiary_name": "Bluebird Demo Services Private Limited",
            "account_number": "001234567890",
            "ifsc": "HDFC0001234",
        },
        {
            "prefix": "blocked_vendor",
            "scenario": "Exact match to synthetic internal prohibited-vendor policy",
            "legal_name": "Northstar Demo Supplies Private Limited",
            "gstin": "29AAPFU0939F1ZR",
            "beneficiary_name": "Northstar Demo Supplies Private Limited",
            "account_number": "007700660055",
            "ifsc": "SBIN0002468",
        },
    ]
    for scenario in scenarios:
        create_pdf(
            f"{scenario['prefix']}_gst.pdf",
            "Fictional GST Registration Extract",
            scenario["scenario"],
            [
                ("Legal Name", scenario["legal_name"]),
                ("GSTIN", scenario["gstin"]),
                ("Status", "Synthetic demo only"),
            ],
        )
        create_pdf(
            f"{scenario['prefix']}_bank.pdf",
            "Fictional Bank Proof Extract",
            scenario["scenario"],
            [
                ("Beneficiary Name", scenario["beneficiary_name"]),
                ("Account Number", scenario["account_number"]),
                ("IFSC", scenario["ifsc"]),
                ("Status", "Synthetic demo only"),
            ],
        )


if __name__ == "__main__":
    main()
