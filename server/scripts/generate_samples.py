"""Generate the sample corpus in ``samples/``. Decision D67.

Run from ``server/``:

    uv run python scripts/generate_samples.py

The files it writes are committed, so nobody needs to run this to try the product. It exists
because a corpus nobody can regenerate is a corpus nobody can correct: when a document needs
a different label or one more line, the fix belongs here rather than in a binary.

WHAT THE CORPUS IS FOR
----------------------
Every document earns its place by exercising something the demo claims (requirements section
8), and the manifest records which. In particular the set is deliberately INCONSISTENT about
naming: the same fact appears as "Total due", "Grand total" and "Amount payable", and the
party sending the invoice is "Vendor", "Supplier" and "Billed by". A corpus where every
document agrees would demonstrate nothing, because agreeing is the easy case.

Dates are written five different ways for the same reason.

Every organisation here is fictional, and every figure is invented. The arithmetic within and
across documents is nevertheless consistent, because a reviewer who adds up the invoices by
hand and finds they disagree with the dashboard has learned something false about the system.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from docx import Document as DocxDocument
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"

BUYER = "Northwind Trading Company"
BUYER_ADDRESS = ["114 Harbour Road", "Portsmouth, NH 03801", "United States"]

PAGE_WIDTH, PAGE_HEIGHT = LETTER
LEFT = inch
RIGHT = PAGE_WIDTH - inch
TOP = PAGE_HEIGHT - inch


# ---------------------------------------------------------------------------
# The facts. One place, so every document agrees with every other.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Invoice:
    vendor: str
    number: str
    issued: str
    """As the document writes it. Deliberately a different format per document."""
    purchase_order: str | None
    subtotal: float
    tax: float
    tax_label: str
    total: float
    terms: str
    lines: list[tuple[str, int, float]]

    def check(self) -> None:
        """Fail loudly rather than ship a document whose own figures disagree."""
        line_total = round(sum(quantity * price for _, quantity, price in self.lines), 2)
        assert line_total == self.subtotal, f"{self.number}: lines {line_total} != subtotal"
        assert round(self.subtotal + self.tax, 2) == self.total, f"{self.number}: total"


ACME_JANUARY = Invoice(
    vendor="Acme Industrial Supplies Ltd",
    number="INV-2041",
    issued="14 January 2026",
    purchase_order="PO-4471",
    subtotal=4200.00,
    tax=756.00,
    tax_label="Sales tax (18%)",
    total=4956.00,
    terms="Net 30",
    lines=[
        ("Steel shelving unit, 2400mm", 6, 480.00),
        ("Anti-static workbench mat", 24, 42.50),
        ("Delivery and installation", 1, 300.00),
    ],
)

ACME_FEBRUARY = Invoice(
    vendor="Acme Industrial Supplies Ltd",
    number="INV-2098",
    issued="11 February 2026",
    purchase_order="PO-4503",
    subtotal=2600.00,
    tax=468.00,
    tax_label="Sales tax (18%)",
    total=3068.00,
    terms="Net 30",
    lines=[
        ("Replacement castor set", 40, 32.50),
        ("Steel shelving unit, 1800mm", 3, 420.00),
        ("Delivery", 1, 40.00),
    ],
)

GLOBEX = Invoice(
    vendor="Globex Corporation",
    number="GX-7781",
    issued="2026-02-03",
    purchase_order=None,  # the missing-purchase-order demo depends on this
    subtotal=1000.00,
    tax=200.00,
    tax_label="VAT (20%)",
    total=1200.00,
    terms="Net 15",
    lines=[
        ("Quarterly compliance review", 1, 750.00),
        ("Document handling charge", 5, 50.00),
    ],
)

INITECH = Invoice(
    vendor="Initech Systems Inc",
    number="INT-5567",
    issued="March 5, 2026",
    purchase_order="PO-4610",
    subtotal=6000.00,
    tax=510.00,
    tax_label="Sales tax (8.5%)",
    total=6510.00,
    terms="Net 45",
    lines=[
        ("Workstation refresh, per seat", 20, 275.00),
        ("On-site configuration, per day", 4, 125.00),
    ],
)

UMBRELLA = Invoice(
    vendor="Umbrella Logistics LLC",
    number="UL-0442",
    issued="Mar 18, 2026",
    purchase_order=None,
    subtotal=845.00,
    tax=45.50,
    tax_label="Fuel surcharge",
    total=890.50,
    terms="Due on receipt",
    lines=[
        ("Pallet freight, Portsmouth to Albany", 5, 145.00),
        ("Overnight storage", 4, 30.00),
    ],
)

HOOLI = Invoice(
    vendor="Hooli Print Services",
    number="R-2291",
    issued="22/03/2026",
    purchase_order=None,
    subtotal=120.00,
    tax=8.40,
    tax_label="Tax",
    total=128.40,
    terms="Paid by card",
    lines=[("Large format print, A0", 8, 15.00)],
)

INVOICES = [ACME_JANUARY, ACME_FEBRUARY, GLOBEX, INITECH, UMBRELLA, HOOLI]

VENDOR_TOTALS = {
    "Acme Industrial Supplies Ltd": 8024.00,
    "Globex Corporation": 1200.00,
    "Initech Systems Inc": 6510.00,
    "Umbrella Logistics LLC": 890.50,
    "Hooli Print Services": 128.40,
}
"""What "total amount by vendor" must come to. Asserted below against the invoices
themselves, so this cannot drift away from the documents."""


def money(amount: float) -> str:
    return f"{amount:,.2f}"


# ---------------------------------------------------------------------------
# Portable Document Format
# ---------------------------------------------------------------------------


def invoice_pdf(path: Path, invoice: Invoice, *, vendor_address: list[str]) -> None:
    """A conventional invoice: vendor block, meta table, line items, totals.

    Laid out with real coordinates rather than as a wall of text, because the provenance
    highlight is only meaningful if the value sits somewhere a person would look for it.
    """
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.setTitle(f"{invoice.vendor} {invoice.number}")

    # A caption over the letterhead, mirroring the "Bill to" block below it. Without one,
    # the extracted label for this field is the company's own name, and a label that IS the
    # value cannot be matched against another document's "Seller" or "Vendor name".
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(LEFT, TOP, "Vendor")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(LEFT, TOP - 18, invoice.vendor)
    pdf.setFont("Helvetica", 9)
    y = TOP - 34
    for line in vendor_address:
        pdf.drawString(LEFT, y, line)
        y -= 12

    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawRightString(RIGHT, TOP, "INVOICE")

    pdf.setFont("Helvetica", 10)
    meta = [
        ("Invoice number", invoice.number),
        ("Invoice date", invoice.issued),
        ("Payment terms", invoice.terms),
    ]
    if invoice.purchase_order:
        # Absent, not "none supplied". A field whose value is the word "none" is present as
        # far as any query is concerned, and "which invoices are missing a purchase order"
        # would answer zero while being perfectly correct about the data it was given.
        meta.insert(2, ("Purchase order", invoice.purchase_order))
    meta_y = TOP - 34
    for label, value in meta:
        pdf.drawRightString(RIGHT - 110, meta_y, f"{label}:")
        pdf.drawRightString(RIGHT, meta_y, value)
        meta_y -= 14

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(LEFT, y - 24, "Bill to")
    pdf.setFont("Helvetica", 10)
    bill_y = y - 38
    for line in [BUYER, *BUYER_ADDRESS]:
        pdf.drawString(LEFT, bill_y, line)
        bill_y -= 12

    table_top = min(bill_y, meta_y) - 24
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(LEFT, table_top, "Description")
    pdf.drawRightString(RIGHT - 200, table_top, "Qty")
    pdf.drawRightString(RIGHT - 100, table_top, "Unit price")
    pdf.drawRightString(RIGHT, table_top, "Amount")
    pdf.setLineWidth(0.5)
    pdf.line(LEFT, table_top - 6, RIGHT, table_top - 6)

    pdf.setFont("Helvetica", 10)
    row_y = table_top - 22
    for description, quantity, price in invoice.lines:
        pdf.drawString(LEFT, row_y, description)
        pdf.drawRightString(RIGHT - 200, row_y, str(quantity))
        pdf.drawRightString(RIGHT - 100, row_y, money(price))
        pdf.drawRightString(RIGHT, row_y, money(quantity * price))
        row_y -= 16

    pdf.line(LEFT, row_y - 2, RIGHT, row_y - 2)
    totals = [
        ("Subtotal", money(invoice.subtotal)),
        (invoice.tax_label, money(invoice.tax)),
        ("Total due", f"{money(invoice.total)} USD"),
    ]
    total_y = row_y - 20
    for index, (label, value) in enumerate(totals):
        pdf.setFont("Helvetica-Bold" if index == len(totals) - 1 else "Helvetica", 10)
        pdf.drawRightString(RIGHT - 100, total_y, f"{label}:")
        pdf.drawRightString(RIGHT, total_y, value)
        total_y -= 15

    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(LEFT, inch, f"Payment terms: {invoice.terms}. Remit to account 5520-88431.")
    pdf.showPage()
    pdf.save()


def wrapped(pdf: canvas.Canvas, text: str, x: float, y: float, width: float,
            *, font: str = "Helvetica", size: int = 10, leading: int = 14) -> float:
    """Draw ``text`` wrapped to ``width``, returning the y position below it."""
    pdf.setFont(font, size)
    words = text.split()
    line: list[str] = []
    for word in words:
        candidate = " ".join([*line, word])
        if pdf.stringWidth(candidate, font, size) > width and line:
            pdf.drawString(x, y, " ".join(line))
            y -= leading
            line = [word]
        else:
            line = [*line, word]
    if line:
        pdf.drawString(x, y, " ".join(line))
        y -= leading
    return y


def services_agreement(path: Path) -> None:
    """Two pages of prose. The retrieval demo needs something that is not a table, and the
    payment-terms clause is what "what does the contract say about payment terms" finds.

    The purchase-order sentence in clause 3 is deliberate: it is what makes "which invoices
    are missing a purchase order" a question with consequences rather than a curiosity."""
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.setTitle("Master Services Agreement")

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawCentredString(PAGE_WIDTH / 2, TOP, "MASTER SERVICES AGREEMENT")
    pdf.setFont("Helvetica", 10)
    y = TOP - 30
    y = wrapped(
        pdf,
        f"This Master Services Agreement (the “Agreement”) is entered into on "
        f"5 January 2026 between {ACME_JANUARY.vendor}, a company registered in Delaware "
        f"(the “Supplier”), and {BUYER}, a company registered in New Hampshire "
        f"(the “Customer”).",
        LEFT, y, RIGHT - LEFT,
    )
    y -= 10

    clauses_page_one = [
        (
            "1. Term",
            "This Agreement commences on the date above and continues for an initial "
            "period of twelve (12) months. It renews automatically for successive "
            "twelve-month periods unless either party gives written notice of "
            "non-renewal at least sixty (60) days before the end of the then-current "
            "period.",
        ),
        (
            "2. Scope of services",
            "The Supplier shall provide industrial shelving, workbench equipment, and "
            "associated delivery and installation services as described in each purchase "
            "order accepted by the Supplier. No purchase order is binding on the Supplier "
            "until acknowledged in writing.",
        ),
        (
            "3. Fees and payment",
            "The Customer shall pay each undisputed invoice within thirty (30) days of "
            "the invoice date. Invoices are issued in United States dollars. Every "
            "invoice must quote the purchase order number against which it is raised; "
            "the Customer may return an invoice that does not quote a purchase order "
            "number, and the payment period for a returned invoice begins again on "
            "reissue. Amounts remaining unpaid after the due date accrue interest at one "
            "and one half percent (1.5%) per month, or the maximum rate permitted by "
            "law, whichever is lower.",
        ),
        (
            "4. Disputed amounts",
            "The Customer may withhold payment of any amount it disputes in good faith, "
            "provided it notifies the Supplier in writing within fifteen (15) days of the "
            "invoice date and pays the undisputed remainder when due.",
        ),
    ]
    for heading, body in clauses_page_one:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(LEFT, y, heading)
        y -= 14
        y = wrapped(pdf, body, LEFT, y, RIGHT - LEFT)
        y -= 8

    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(PAGE_WIDTH / 2, 0.75 * inch, "Page 1 of 2")
    pdf.showPage()

    y = TOP
    clauses_page_two = [
        (
            "5. Confidentiality",
            "Each party shall keep confidential all information disclosed by the other "
            "that is marked confidential or would reasonably be understood to be "
            "confidential, and shall not disclose it to any third party except to its "
            "own personnel and advisers who need to know it.",
        ),
        (
            "6. Warranty",
            "The Supplier warrants that goods supplied will be free from material defects "
            "for twelve (12) months from delivery, and that services will be performed "
            "with reasonable skill and care.",
        ),
        (
            "7. Limitation of liability",
            "Neither party is liable for indirect or consequential loss. Each party's "
            "total aggregate liability under this Agreement is limited to the total "
            "amount paid by the Customer in the twelve months preceding the event giving "
            "rise to the claim.",
        ),
        (
            "8. Termination",
            "Either party may terminate this Agreement on thirty (30) days written "
            "notice. Either party may terminate immediately if the other commits a "
            "material breach that is not remedied within fourteen (14) days of written "
            "notice of that breach.",
        ),
        (
            "9. Governing law",
            "This Agreement is governed by the laws of the State of Delaware, and the "
            "parties submit to the exclusive jurisdiction of its courts.",
        ),
    ]
    for heading, body in clauses_page_two:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(LEFT, y, heading)
        y -= 14
        y = wrapped(pdf, body, LEFT, y, RIGHT - LEFT)
        y -= 8

    y -= 20
    pdf.setFont("Helvetica", 10)
    pdf.drawString(LEFT, y, "Signed for and on behalf of the Supplier:")
    pdf.drawString(LEFT, y - 30, "________________________")
    pdf.drawString(LEFT, y - 44, "D. Ferreira, Commercial Director")
    pdf.drawString(PAGE_WIDTH / 2, y, "Signed for and on behalf of the Customer:")
    pdf.drawString(PAGE_WIDTH / 2, y - 30, "________________________")
    pdf.drawString(PAGE_WIDTH / 2, y - 44, "M. Okonjo, Head of Operations")

    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(PAGE_WIDTH / 2, 0.75 * inch, "Page 2 of 2")
    pdf.showPage()
    pdf.save()


def bank_statement(path: Path) -> None:
    """A document of an entirely different kind, which is the point of it.

    Its fields barely overlap the invoices': it has an account number and a closing balance
    and no vendor at all. A schema that copes with that is a schema that is not quietly an
    invoice schema, which is the domain-agnostic claim the requirements make."""
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.setTitle("Statement of account, March 2026")

    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(LEFT, TOP, "Seaboard Commercial Bank")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(LEFT, TOP - 18, "Statement of account")

    meta = [
        ("Account holder", BUYER),
        ("Account number", "8841-22019"),
        ("Statement period", "1 March 2026 to 31 March 2026"),
        ("Opening balance", f"{money(184320.55)} USD"),
        ("Closing balance", f"{money(171951.65)} USD"),
    ]
    y = TOP - 44
    for label, value in meta:
        pdf.setFont("Helvetica", 10)
        pdf.drawString(LEFT, y, f"{label}:")
        pdf.drawString(LEFT + 130, y, value)
        y -= 14

    y -= 12
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(LEFT, y, "Date")
    pdf.drawString(LEFT + 80, y, "Description")
    pdf.drawRightString(RIGHT - 110, y, "Debit")
    pdf.drawRightString(RIGHT, y, "Balance")
    pdf.line(LEFT, y - 6, RIGHT, y - 6)

    rows = [
        ("02 Mar 2026", "Payment, Globex Corporation, GX-7781", 1200.00, 183120.55),
        ("09 Mar 2026", "Payment, Acme Industrial Supplies, INV-2041", 4956.00, 178164.55),
        ("16 Mar 2026", "Payroll transfer", 3200.00, 174964.55),
        ("24 Mar 2026", "Payment, Umbrella Logistics, UL-0442", 890.50, 174074.05),
        ("30 Mar 2026", "Card settlement, Hooli Print Services", 128.40, 173945.65),
        ("31 Mar 2026", "Bank charges", 1994.00, 171951.65),
    ]
    pdf.setFont("Helvetica", 10)
    y -= 22
    for date_text, description, debit, balance in rows:
        pdf.drawString(LEFT, y, date_text)
        pdf.drawString(LEFT + 80, y, description)
        pdf.drawRightString(RIGHT - 110, y, money(debit))
        pdf.drawRightString(RIGHT, y, money(balance))
        y -= 15

    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(LEFT, y - 14, "Please report any discrepancy within 30 days.")
    pdf.showPage()
    pdf.save()


# ---------------------------------------------------------------------------
# Word and spreadsheet
# ---------------------------------------------------------------------------


def globex_invoice_docx(path: Path) -> None:
    """The drift document. It calls the vendor a "Supplier", the number an "Invoice No",
    and the total a "Grand total", and it carries no purchase order at all."""
    document = DocxDocument()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    document.add_heading(GLOBEX.vendor, level=0)
    document.add_paragraph("Rue de la Loi 227, 1040 Brussels, Belgium")
    document.add_heading("Invoice", level=1)

    meta = document.add_table(rows=0, cols=2)
    for label, value in [
        ("Seller", GLOBEX.vendor),
        ("Invoice No", GLOBEX.number),
        ("Invoice date", GLOBEX.issued),
        ("Customer", BUYER),
        ("Payment terms", GLOBEX.terms),
    ]:
        row = meta.add_row().cells
        row[0].text = label
        row[1].text = value

    document.add_paragraph()
    table = document.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    header = table.rows[0].cells
    header[0].text = "Service"
    header[1].text = "Qty"
    header[2].text = "Amount"
    for description, quantity, price in GLOBEX.lines:
        cells = table.add_row().cells
        cells[0].text = description
        cells[1].text = str(quantity)
        cells[2].text = money(quantity * price)

    document.add_paragraph()
    document.add_paragraph(f"Amount before tax: {money(GLOBEX.subtotal)} USD")
    document.add_paragraph(f"{GLOBEX.tax_label}: {money(GLOBEX.tax)} USD")
    document.add_paragraph(f"Amount due: {money(GLOBEX.total)} USD")
    document.add_paragraph()
    document.add_paragraph(
        "No purchase order number was supplied by the customer for this engagement."
    )
    document.save(path)


def expense_policy_docx(path: Path) -> None:
    """A second prose document, and one that is not about invoices at all."""
    document = DocxDocument()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    document.add_heading("Travel and Expense Policy", level=0)
    document.add_paragraph("Northwind Trading Company · Effective 1 February 2026 · Version 3.1")

    sections = [
        (
            "Purpose",
            "This policy sets out how employees of Northwind Trading Company may incur and "
            "reclaim business expenses, and what approval is required before doing so.",
        ),
        (
            "Receipts",
            "An itemised receipt is required for every expense of 75.00 USD or more. Card "
            "statements are not accepted as receipts. Expenses submitted without a valid "
            "receipt may be reimbursed at the approver's discretion, once per employee per "
            "financial year.",
        ),
        (
            "Approval thresholds",
            "Expenses up to 1,000.00 USD are approved by the employee's line manager. "
            "Expenses above 1,000.00 USD and up to 10,000.00 USD require director approval. "
            "Any commitment above 10,000.00 USD requires the Chief Financial Officer and a "
            "purchase order raised before the commitment is made.",
        ),
        (
            "Submission and reimbursement",
            "Claims must be submitted within thirty (30) days of the expense being incurred. "
            "Approved claims are reimbursed in the next payroll run following approval.",
        ),
        (
            "Travel",
            "Standard class rail and economy air travel are the default. Business class air "
            "travel requires director approval and is permitted only for flights with a "
            "scheduled duration over eight hours. Accommodation is capped at 220.00 USD per "
            "night in metropolitan areas and 150.00 USD elsewhere.",
        ),
        (
            "Non-reimbursable",
            "Fines, personal entertainment, in-room minibar charges, and travel undertaken "
            "without prior approval are not reimbursable.",
        ),
    ]
    for heading, body in sections:
        document.add_heading(heading, level=1)
        document.add_paragraph(body)
    document.save(path)


def initech_invoice_xlsx(path: Path) -> None:
    """A spreadsheet invoice, using a third vocabulary again: "Billed by", "Reference",
    "Net amount", "Amount payable"."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 38
    sheet.column_dimensions["C"].width = 10
    sheet.column_dimensions["D"].width = 14

    rows: list[tuple[str, str, str, str]] = [
        ("Vendor name", INITECH.vendor, "", ""),
        ("Billed to", BUYER, "", ""),
        ("Document number", INITECH.number, "", ""),
        ("Invoice date", INITECH.issued, "", ""),
        ("Purchase order", INITECH.purchase_order or "", "", ""),
        ("Payment terms", INITECH.terms, "", ""),
        ("", "", "", ""),
        ("Item", "Description", "Qty", "Amount"),
    ]
    for index, (label, value, third, fourth) in enumerate(rows, start=1):
        sheet.cell(row=index, column=1, value=label)
        sheet.cell(row=index, column=2, value=value)
        sheet.cell(row=index, column=3, value=third)
        sheet.cell(row=index, column=4, value=fourth)

    header_row = len(rows)
    for column in range(1, 5):
        sheet.cell(row=header_row, column=column).font = Font(bold=True)

    row_index = header_row + 1
    for number, (description, quantity, price) in enumerate(INITECH.lines, start=1):
        sheet.cell(row=row_index, column=1, value=f"{number:02d}")
        sheet.cell(row=row_index, column=2, value=description)
        sheet.cell(row=row_index, column=3, value=quantity)
        cell = sheet.cell(row=row_index, column=4, value=round(quantity * price, 2))
        cell.number_format = "#,##0.00"
        row_index += 1

    row_index += 1
    for label, amount, bold in [
        ("Net amount", INITECH.subtotal, False),
        (INITECH.tax_label, INITECH.tax, False),
        ("Amount now due (USD)", INITECH.total, True),
    ]:
        sheet.cell(row=row_index, column=2, value=label).alignment = Alignment(horizontal="right")
        cell = sheet.cell(row=row_index, column=4, value=amount)
        cell.number_format = "#,##0.00"
        if bold:
            sheet.cell(row=row_index, column=2).font = Font(bold=True)
            cell.font = Font(bold=True)
        row_index += 1

    workbook.save(path)


# ---------------------------------------------------------------------------
# Plain text, comma-separated values, and a scan
# ---------------------------------------------------------------------------


def umbrella_invoice_txt(path: Path) -> None:
    """The plainest possible input: a fixed-width text invoice, the kind a logistics system
    emails out. No layout to lean on, so extraction has only the words."""
    lines = [
        "UMBRELLA LOGISTICS LLC",
        "2100 Dock Street, Albany, NY 12202",
        "",
        f"INVOICE {UMBRELLA.number}",
        f"Seller: {UMBRELLA.vendor}",
        f"Invoice date: {UMBRELLA.issued}",
        f"Bill to: {BUYER}",
        "",
        "Description                                  Qty     Amount",
        "-----------------------------------------------------------",
    ]
    for description, quantity, price in UMBRELLA.lines:
        lines.append(f"{description:<44}{quantity:>4}{money(quantity * price):>11}")
    lines += [
        "-----------------------------------------------------------",
        f"{'Subtotal':<48}{money(UMBRELLA.subtotal):>11}",
        f"{UMBRELLA.tax_label:<48}{money(UMBRELLA.tax):>11}",
        f"{'Balance due now (USD)':<48}{money(UMBRELLA.total):>11}",
        "",
        f"Terms: {UMBRELLA.terms}.",
        "Questions: accounts@umbrella-logistics.example",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def supplier_directory_csv(path: Path) -> None:
    """A reference table rather than a transaction.

    Deliberately carries NO amounts. A comma-separated ledger restating the invoice totals
    would double-count them in "total amount by vendor", and a demo corpus that makes the
    dashboard wrong is worse than one format short."""
    rows = [
        ("Supplier", "Contact", "Email", "Country", "Payment terms", "Currency"),
        (
            "Acme Industrial Supplies Ltd", "D. Ferreira",
            "accounts@acme-industrial.example", "United States", "Net 30", "USD",
        ),
        (
            "Globex Corporation", "S. Lindqvist",
            "billing@globex.example", "Belgium", "Net 15", "USD",
        ),
        (
            "Initech Systems Inc", "P. Aranda",
            "ar@initech-systems.example", "United States", "Net 45", "USD",
        ),
        (
            "Umbrella Logistics LLC", "T. Boateng",
            "accounts@umbrella-logistics.example", "United States", "Due on receipt", "USD",
        ),
        (
            "Hooli Print Services", "R. Whitfield",
            "hello@hooli-print.example", "United States", "Paid by card", "USD",
        ),
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _font(size: int, *, mono: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A real font if the system has one. Optical Character Recognition on the default
    bitmap font is unreliable, and an unreadable sample would test nothing."""
    candidates = (
        ["/System/Library/Fonts/Supplemental/Courier New.ttf",
         "/System/Library/Fonts/Menlo.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
        if mono
        else ["/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:  # pragma: no cover - a font that exists but will not load
                continue
    return ImageFont.load_default()


def hooli_receipt_png(path: Path) -> None:
    """A photographed receipt, so the corpus exercises the Optical Character Recognition
    path rather than only documents with a text layer.

    Rendered dark-on-light at 200 dots per inch with a slightly uneven background: enough to
    look scanned, not so much that the sample becomes a test of Tesseract's bad day."""
    width, height = 720, 980
    image = Image.new("L", (width, height), color=246)
    draw = ImageDraw.Draw(image)

    # A faint vertical gradient, the way a flatbed scan falls off toward one edge.
    for y in range(height):
        shade = 246 - int(10 * (y / height))
        draw.line([(0, y), (width, y)], fill=shade)

    title = _font(34, mono=False)
    body = _font(24)
    small = _font(20)

    y = 60
    draw.text((60, y), HOOLI.vendor.upper(), font=title, fill=25)
    y += 46
    draw.text((60, y), "48 Foundry Lane, Nashua, NH", font=small, fill=45)
    y += 28
    draw.text((60, y), "VAT reg 22-8817714", font=small, fill=45)
    y += 44
    draw.line([(60, y), (width - 60, y)], fill=90, width=2)

    y += 30
    for label, value in [
        ("MERCHANT", HOOLI.vendor),
        ("RECEIPT NUMBER", HOOLI.number),
        ("INVOICE DATE", HOOLI.issued),
        ("CUSTOMER", "Northwind Trading"),
    ]:
        draw.text((60, y), f"{label}  {value}", font=small, fill=25)
        y += 32

    y += 16
    draw.line([(60, y), (width - 60, y)], fill=90, width=2)
    y += 26
    for description, quantity, price in HOOLI.lines:
        draw.text((60, y), f"{description}", font=body, fill=25)
        y += 32
        draw.text((60, y), f"{quantity} x {money(price)}", font=body, fill=25)
        draw.text((width - 220, y), money(quantity * price), font=body, fill=25)
        y += 40

    draw.line([(60, y), (width - 60, y)], fill=90, width=2)
    y += 28
    for label, amount in [
        ("SUBTOTAL", HOOLI.subtotal),
        ("TAX", HOOLI.tax),
        ("AMOUNT DUE USD", HOOLI.total),
    ]:
        draw.text((60, y), label, font=body, fill=25)
        draw.text((width - 220, y), money(amount), font=body, fill=25)
        y += 36

    y += 24
    draw.text((60, y), "PAID BY CARD ****4419", font=body, fill=25)
    y += 34
    draw.text((60, y), "THANK YOU FOR YOUR BUSINESS", font=small, fill=60)

    image.save(path, format="PNG", optimize=True)


# ---------------------------------------------------------------------------
# Manifest and ground truth
# ---------------------------------------------------------------------------

DOCUMENTS = [
    {
        "file": "acme-invoice-INV-2041.pdf",
        "kind": "invoice",
        "format": "pdf",
        "why": "Baseline invoice with a purchase order. Says 'Vendor', 'Total due'.",
    },
    {
        "file": "acme-invoice-INV-2098.pdf",
        "kind": "invoice",
        "format": "pdf",
        "why": "Second invoice from the same vendor, so 'total by vendor' has to group.",
    },
    {
        "file": "globex-invoice-GX-7781.docx",
        "kind": "invoice",
        "format": "docx",
        "why": "Calls it 'Supplier', 'Invoice No', 'Grand total'. No purchase order.",
    },
    {
        "file": "initech-invoice-INT-5567.xlsx",
        "kind": "invoice",
        "format": "xlsx",
        "why": "A third vocabulary: 'Billed by', 'Reference', 'Amount payable'.",
    },
    {
        "file": "umbrella-invoice-UL-0442.txt",
        "kind": "invoice",
        "format": "txt",
        "why": "Plain text, no layout to lean on. No purchase order.",
    },
    {
        "file": "hooli-receipt-R-2291.png",
        "kind": "receipt",
        "format": "image",
        "why": "Scanned image, so the Optical Character Recognition path runs. No PO.",
    },
    {
        "file": "acme-services-agreement.pdf",
        "kind": "contract",
        "format": "pdf",
        "why": "Two pages of prose. Answers 'what does the contract say about payment "
               "terms' and explains why a missing purchase order matters.",
    },
    {
        "file": "northwind-expense-policy.docx",
        "kind": "policy",
        "format": "docx",
        "why": "Prose that is not about invoices at all, so the schema cannot quietly "
               "become an invoice schema.",
    },
    {
        "file": "seaboard-statement-march-2026.pdf",
        "kind": "bank statement",
        "format": "pdf",
        "why": "Different fields entirely: account number, closing balance, no vendor.",
    },
    {
        "file": "supplier-directory.csv",
        "kind": "reference table",
        "format": "csv",
        "why": "Tabular reference data with no amounts, so it cannot distort the totals.",
    },
]


def write_manifest(path: Path) -> None:
    manifest = {
        "name": "Distill sample corpus",
        "generated_by": "server/scripts/generate_samples.py",
        "note": (
            "Every organisation and figure here is fictional. The set is deliberately "
            "inconsistent about field naming and date format; see decision D67."
        ),
        "documents": DOCUMENTS,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def write_expected(path: Path) -> None:
    """Ground truth, for checking extraction by eye or by test.

    Not read by the application. It is here because a sample corpus without an answer key
    can only be assessed by whether the output looks plausible, which is exactly the
    judgement this product exists to replace."""
    expected = {
        "note": "Ground truth for the sample corpus. Not read by the server.",
        "invoices": [
            {
                "file": entry["file"],
                "vendor": invoice.vendor,
                "invoice_number": invoice.number,
                "invoice_date_as_written": invoice.issued,
                "purchase_order": invoice.purchase_order,
                "subtotal": invoice.subtotal,
                "tax": invoice.tax,
                "total": invoice.total,
                "currency": "USD",
                "payment_terms": invoice.terms,
            }
            for entry, invoice in zip(
                [DOCUMENTS[0], DOCUMENTS[1], DOCUMENTS[2], DOCUMENTS[3], DOCUMENTS[4],
                 DOCUMENTS[5]],
                INVOICES,
                strict=True,
            )
        ],
        "totals_by_vendor_usd": VENDOR_TOTALS,
        "grand_total_usd": round(sum(VENDOR_TOTALS.values()), 2),
        "invoices_missing_a_purchase_order": [
            invoice.number for invoice in INVOICES if invoice.purchase_order is None
        ],
        "contract_payment_terms": (
            "Thirty (30) days from the invoice date; 1.5% per month interest on late "
            "amounts; every invoice must quote a purchase order number."
        ),
        "expense_policy_receipt_threshold_usd": 75.00,
        "bank_statement_closing_balance_usd": 171951.65,
    }
    path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for invoice in INVOICES:
        invoice.check()
    computed: dict[str, float] = {}
    for invoice in INVOICES:
        computed[invoice.vendor] = round(computed.get(invoice.vendor, 0.0) + invoice.total, 2)
    assert computed == VENDOR_TOTALS, f"vendor totals drifted: {computed}"

    SAMPLES.mkdir(parents=True, exist_ok=True)

    invoice_pdf(
        SAMPLES / "acme-invoice-INV-2041.pdf", ACME_JANUARY,
        vendor_address=["9 Foundry Park", "Wilmington, DE 19801", "United States"],
    )
    invoice_pdf(
        SAMPLES / "acme-invoice-INV-2098.pdf", ACME_FEBRUARY,
        vendor_address=["9 Foundry Park", "Wilmington, DE 19801", "United States"],
    )
    globex_invoice_docx(SAMPLES / "globex-invoice-GX-7781.docx")
    initech_invoice_xlsx(SAMPLES / "initech-invoice-INT-5567.xlsx")
    umbrella_invoice_txt(SAMPLES / "umbrella-invoice-UL-0442.txt")
    hooli_receipt_png(SAMPLES / "hooli-receipt-R-2291.png")
    services_agreement(SAMPLES / "acme-services-agreement.pdf")
    expense_policy_docx(SAMPLES / "northwind-expense-policy.docx")
    bank_statement(SAMPLES / "seaboard-statement-march-2026.pdf")
    supplier_directory_csv(SAMPLES / "supplier-directory.csv")
    write_manifest(SAMPLES / "manifest.json")
    write_expected(SAMPLES / "expected.json")

    for entry in DOCUMENTS:
        target = SAMPLES / str(entry["file"])
        assert target.is_file(), f"manifest lists {entry['file']}, which was not written"
        print(f"  {target.name:38s} {target.stat().st_size / 1024:7.1f} KB")
    print(f"\n{len(DOCUMENTS)} documents written to {SAMPLES}")


if __name__ == "__main__":
    main()
