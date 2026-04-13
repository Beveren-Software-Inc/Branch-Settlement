# Copyright (c) 2026, Balachandar S and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import flt, getdate


class BranchSettlement(frappe.model.document.Document):

    def validate(self):
        self._validate_allocated_amounts()
        self._set_received_amount()

    def before_cancel(self):
        self.ignore_linked_doctypes = ["Journal Entry"]

    def _validate_allocated_amounts(self):
        for row in self.payment_references:
            if not row.sub_branch:
                frappe.throw(_("Row {0}: Sub Branch is missing.").format(row.idx))
            if flt(row.allocated_amount) <= 0:
                frappe.throw(
                    _("Row {0}: Allocated Amount must be greater than zero.").format(row.idx)
                )
            if flt(row.allocated_amount) > flt(row.outstanding_amount):
                frappe.throw(
                    _("Row {0}: Allocated Amount ({1}) cannot exceed Outstanding Amount ({2}).").format(
                        row.idx, row.allocated_amount, row.outstanding_amount
                    )
                )

    def _set_received_amount(self):
        self.received_amount = sum(flt(r.allocated_amount) for r in self.payment_references)

    def on_submit(self):
        self._create_journal_entry()

    def on_cancel(self):
        self._cancel_journal_entry()

    def _create_journal_entry(self):
        if not self.payment_references:
            frappe.throw(_("No payment references found. Cannot create Journal Entry."))

        head_branch_account = self._get_receivable_account(self.head_branch)

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = self.posting_date
        je.company      = self.company
        je.user_remark  = _("Branch Settlement: {0}").format(self.name)

        # Single Debit — Head Branch, total received amount
        je.append("accounts", {
            "account":                    head_branch_account,
            "party_type":                 "Customer",
            "party":                      self.head_branch,
            "debit_in_account_currency":  flt(self.received_amount),
            "credit_in_account_currency": 0,
            "reference_type":             "Branch Settlement",
            "reference_name":             self.name,
            "user_remark":                _("Branch Settlement: {0}").format(self.name),
        })

        # One Credit per row — Sub Branch + Sales Invoice reference
        for row in self.payment_references:
            sub_branch_account = self._get_receivable_account(row.sub_branch)
            je.append("accounts", {
                "account":                    sub_branch_account,
                "party_type":                 "Customer",
                "party":                      row.sub_branch,
                "debit_in_account_currency":  0,
                "credit_in_account_currency": flt(row.allocated_amount),
                "reference_type":             "Sales Invoice",
                "reference_name":             row.reference_name,
                "user_remark":                _("Against Invoice: {0}").format(row.reference_name),
            })

        je.flags.ignore_permissions = True
        je.insert()
        je.submit()

        frappe.db.set_value("Branch Settlement", self.name, "journal_entry", je.name)
        frappe.msgprint(
            _("Journal Entry {0} created successfully.").format(frappe.utils.bold(je.name)),
            indicator="green",
            alert=True,
        )

    def _cancel_journal_entry(self):
        je_name = frappe.db.get_value("Branch Settlement", self.name, "journal_entry")
        if not je_name or not frappe.db.exists("Journal Entry", je_name):
            return
 
        je_doc = frappe.get_doc("Journal Entry", je_name)
        if je_doc.docstatus != 1:
            return
 
        # Step 1: Unreconcile all Payment Ledger Entries linked to this JE.
        # This restores the outstanding_amount on each Sales Invoice before cancel.
        self._unreconcile_journal_entry(je_doc)
 
        # Step 2: Cancel the JE — ignore all doctypes that could block cancellation.
        # This mirrors the ignore list from journal_entry.js (ignore_doctypes_on_cancel_all)
        # and Payment Entry's on_cancel ignore list.
        je_doc.ignore_linked_doctypes = [
            "Branch Settlement",
            "Sales Invoice",
            "Purchase Invoice",
            "GL Entry",
            "Payment Ledger Entry",
            "Repost Payment Ledger",
            "Repost Payment Ledger Items",
            "Repost Accounting Ledger",
            "Repost Accounting Ledger Items",
            "Unreconcile Payment",
            "Unreconcile Payment Entries",
            "Bank Transaction",
        ]
        je_doc.flags.ignore_permissions = True
        je_doc.cancel()
        frappe.msgprint(_("Journal Entry {0} cancelled.").format(je_name), alert=True)


    def _unreconcile_journal_entry(self, je_doc):
        """
        Unreconcile all Sales Invoice allocations made by this Journal Entry.
        Uses ERPNext's Unreconcile Payment doctype — same mechanism as the
        'Unreconcile' button on Payment Entry / Journal Entry forms.
        """
        try:
            from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
                get_linked_payments_for_unreconciliation,
            )
 
            # Fetch all reconciled entries linked to this JE
            linked_docs = get_linked_payments_for_unreconciliation(
                voucher_type="Journal Entry",
                voucher_no=je_doc.name,
                party_type="Customer",
                party=None,
                account=None,
                company=self.company,
            )
 
            if not linked_docs:
                return
 
            # Create and submit an Unreconcile Payment doc to delink all allocations
            unreconcile = frappe.new_doc("Unreconcile Payment")
            unreconcile.company   = self.company
            unreconcile.voucher_type = "Journal Entry"
            unreconcile.voucher_no   = je_doc.name
 
            for entry in linked_docs:
                unreconcile.append("allocations", entry)
 
            unreconcile.flags.ignore_permissions = True
            unreconcile.insert()
            unreconcile.submit()
 
        except (ImportError, Exception) as e:
            # Fallback for older ERPNext versions that don't have Unreconcile Payment
            # Directly delink Payment Ledger Entries instead
            frappe.log_error(
                title="Branch Settlement: Unreconcile fallback used",
                message=str(e),
            )
            self._delink_payment_ledger_entries(je_doc.name)


    def _delink_payment_ledger_entries(self, je_name):
        """
        Fallback: directly mark Payment Ledger Entries as delinked.
        Used on older ERPNext versions without the Unreconcile Payment doctype.
        """
        ple = frappe.qb.DocType("Payment Ledger Entry")
        (
            frappe.qb.update(ple)
            .set(ple.delinked, 1)
            .where(
                (ple.voucher_type == "Journal Entry")
                & (ple.voucher_no == je_name)
                & (ple.delinked == 0)
            )
            .run()
        )


    def _get_receivable_account(self, customer):
        account = frappe.db.get_value(
            "Party Account",
            {"parenttype": "Customer", "parent": customer, "company": self.company},
            "account",
        )
        if not account:
            account = frappe.db.get_value("Company", self.company, "default_receivable_account")
        if not account:
            frappe.throw(
                _("Receivable account not found for customer {0}.").format(customer)
            )
        return account


@frappe.whitelist()
def get_outstanding_invoices(
    head_branch,
    company,
    posting_date,
    from_posting_date=None,
    to_posting_date=None,
    outstanding_amt_greater_than=0,
    outstanding_amt_less_than=None,
):
    """
    1. Find all sub-branch customers whose custom_head_branch = head_branch
    2. Fetch their outstanding Sales Invoices, applying the same filters
       used by Payment Entry's Get Outstanding Invoices dialog.
    """

    sub_branches = frappe.get_all(
        "Customer",
        filters={"custom_head_branch": head_branch, "disabled": 0},
        pluck="name",
    )

    if not sub_branches:
        return []

    # ── Build dynamic WHERE clauses for optional filters ─────────────────────
    conditions = """
        si.customer        IN %(sub_branches)s
        AND si.company     = %(company)s
        AND si.docstatus   = 1
        AND si.outstanding_amount > 0
        AND si.posting_date <= %(posting_date)s
    """

    args = {
        "sub_branches": sub_branches,
        "company":      company,
        "posting_date": posting_date,
    }

    if from_posting_date:
        conditions += " AND si.posting_date >= %(from_posting_date)s"
        args["from_posting_date"] = from_posting_date

    if to_posting_date:
        conditions += " AND si.posting_date <= %(to_posting_date)s"
        args["to_posting_date"] = to_posting_date

    invoices = frappe.db.sql(
        f"""
        SELECT
            si.name,
            si.customer,
            si.customer_name,
            si.posting_date,
            si.due_date,
            # si.bill_no,
            si.grand_total,
            si.outstanding_amount,
            si.currency
        FROM
            `tabSales Invoice` si
        WHERE
            {conditions}
        ORDER BY
            si.customer ASC,
            si.due_date ASC,
            si.posting_date ASC
        """,
        args,
        as_dict=True,
    )

    # ── Apply outstanding amount range filter (mirrors Payment Entry logic) ──
    outstanding_amt_greater_than = flt(outstanding_amt_greater_than)
    outstanding_amt_less_than    = flt(outstanding_amt_less_than) if outstanding_amt_less_than else None

    filtered = []
    for inv in invoices:
        outstanding = flt(inv.outstanding_amount)

        if outstanding_amt_greater_than and outstanding <= outstanding_amt_greater_than:
            continue
        if outstanding_amt_less_than and outstanding >= outstanding_amt_less_than:
            continue

        filtered.append(inv)

    return filtered
