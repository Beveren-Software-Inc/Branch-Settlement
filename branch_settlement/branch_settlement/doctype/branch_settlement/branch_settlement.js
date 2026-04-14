// Copyright (c) 2026, Balachandar S and contributors
// For license information, please see license.txt


// Branch Settlement — Client Script
// Place in: branch_settlement/branch_settlement/doctype/branch_settlement/branch_settlement.js

frappe.ui.form.on("Branch Settlement", {

    head_branch: function (frm) {
        frm.clear_table("payment_references");
        frm.refresh_field("payment_references");
        frm.set_value("received_amount", 0);
    },

    company: function (frm) {
        frm.clear_table("payment_references");
        frm.refresh_field("payment_references");
        frm.set_value("received_amount", 0);
    },

    received_amount: function (frm) {
        let remaining_amount = frm.doc.received_amount || 0;

        (frm.doc.payment_references || []).forEach(row => {
            let outstanding = row.outstanding_amount || 0;

            if (remaining_amount > 0) {
                if (remaining_amount >= outstanding) {
                    row.allocated_amount = outstanding;
                    remaining_amount -= outstanding;
                } else {
                    row.allocated_amount = remaining_amount;
                    remaining_amount = 0;
                }
            } else {
                row.allocated_amount = 0;
            }
        });

        frm.refresh_field("payment_references");
    },

    get_outstanding_invoices: function (frm) {
        if (!frm.doc.head_branch) {
            frappe.msgprint(__("Please select a Head Branch first."));
            return;
        }
        if (!frm.doc.company) {
            frappe.msgprint(__("Please select a Company first."));
            return;
        }
        if (!frm.doc.posting_date) {
            frappe.msgprint(__("Please set the Posting Date first."));
            return;
        }

        const dialog = new frappe.ui.Dialog({
            title: __("Get Outstanding Invoices"),
            // fields: [
            //     // Row 1 — Date range
            //     {
            //         label: __("From Posting Date"),
            //         fieldname: "from_posting_date",
            //         fieldtype: "Date",
            //     },
            //     {
            //         fieldname: "col_break_1",
            //         fieldtype: "Column Break",
            //     },
            //     {
            //         label: __("To Posting Date"),
            //         fieldname: "to_posting_date",
            //         fieldtype: "Date",
            //         default: frm.doc.posting_date,
            //     },
            //     // Row 2 — Outstanding amount range
            //     {
            //         fieldname: "section_break_amt",
            //         fieldtype: "Section Break",
            //     },
            //     {
            //         label: __("Outstanding Amount Greater Than"),
            //         fieldname: "outstanding_amt_greater_than",
            //         fieldtype: "Currency",
            //         default: 0,
            //     },
            //     {
            //         fieldname: "col_break_2",
            //         fieldtype: "Column Break",
            //     },
            //     {
            //         label: __("Outstanding Amount Less Than"),
            //         fieldname: "outstanding_amt_less_than",
            //         fieldtype: "Currency",
            //     },
            // ],
            fields: [
                {
                    fieldtype: "Section Break",
                    fieldname: "sec_posting_date",
                    label: __("Posting Date"),
                },
                {
                    fieldtype: "Date",
                    fieldname: "from_posting_date",
                    label: __("From Date"),
                    default: frappe.datetime.add_months(frm.doc.posting_date, -1),
                },
                {
                    fieldtype: "Column Break",
                    fieldname: "col_break_1",
                },
                {
                    fieldtype: "Date",
                    fieldname: "to_posting_date",
                    label: __("To Date"),
                    default: frm.doc.posting_date,
                },
                {
                    fieldtype: "Section Break",
                    fieldname: "sec_due_date",
                    label: __("Due Date"),
                },
                {
                    fieldtype: "Date",
                    fieldname: "from_due_date",
                    label: __("From Date"),
                },
                {
                    fieldtype: "Column Break",
                    fieldname: "col_break_2",
                },
                {
                    fieldtype: "Date",
                    fieldname: "to_due_date",
                    label: __("To Date"),
                },
                {
                    fieldtype: "Section Break",
                    fieldname: "sec_outstanding_amt",
                    label: __("Outstanding Amount"),
                },
                {
                    fieldtype: "Currency",
                    fieldname: "outstanding_amt_greater_than",
                    label: __("Greater Than Amount"),
                    default: 0,
                },
                {
                    fieldtype: "Column Break",
                    fieldname: "col_break_3",
                },
                {
                    fieldtype: "Currency",
                    fieldname: "outstanding_amt_less_than",
                    label: __("Less Than Amount"),
                },
            ],
            primary_action_label: __("Get Invoices"),
            primary_action: function (filters) {
                dialog.hide();

                frappe.call({
                    method: "branch_settlement.branch_settlement.doctype.branch_settlement.branch_settlement.get_outstanding_invoices",
                    args: {
                        head_branch:                    frm.doc.head_branch,
                        company:                        frm.doc.company,
                        posting_date:                   frm.doc.posting_date,
                        from_posting_date:              filters.from_posting_date || null,
                        to_posting_date:                filters.to_posting_date   || frm.doc.posting_date,
                        outstanding_amt_greater_than:   filters.outstanding_amt_greater_than || 0,
                        outstanding_amt_less_than:      filters.outstanding_amt_less_than    || null,
                    },
                    freeze: true,
                    freeze_message: __("Fetching outstanding invoices for all sub branches…"),
                    callback: function (r) {
                        if (!r.message || r.message.length === 0) {
                            frappe.msgprint(
                                __("No outstanding invoices found for any Sub Branch under the selected Head Branch.")
                            );
                            return;
                        }

                        frm.clear_table("payment_references");

                        let total = 0;
                        r.message.forEach(function (inv) {
                            let row = frm.add_child("payment_references");
                            row.sub_branch            = inv.customer;
                            row.customer_name         = inv.customer_name;
                            row.reference_doctype     = "Sales Invoice";
                            row.reference_name        = inv.name;
                            row.due_date              = inv.due_date;
                            row.bill_no               = inv.bill_no || "";
                            row.total_amount          = inv.grand_total;
                            row.outstanding_amount    = inv.outstanding_amount;
                            row.allocated_amount      = inv.outstanding_amount;
                            total += flt(inv.outstanding_amount);
                        });

                        frm.refresh_field("payment_references");
                        frm.set_value("received_amount", total);

                        frappe.show_alert({
                            message: __("{0} invoice(s) fetched.", [r.message.length]),
                            indicator: "green",
                        });
                    },
                });
            },
        });

        dialog.show();
    },
});

frappe.ui.form.on("Branch Settlement Reference", {
    allocated_amount: function (frm) {
        _sync_received_amount(frm);
    },
    payment_references_remove: function (frm) {
        _sync_received_amount(frm);
    },
});

function _sync_received_amount(frm) {
    let total = 0;
    (frm.doc.payment_references || []).forEach(function (row) {
        total += flt(row.allocated_amount);
    });
    frm.set_value("received_amount", total);
}