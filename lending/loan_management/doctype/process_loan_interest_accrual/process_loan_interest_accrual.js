// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// frappe.ui.form.on('Process Loan Interest Accrual', {
// 	refresh: function(frm) {

// 	}
// });

const active_loan_filters = {
					"docstatus": 1,
					"status": ["not in", ["Closed", "Draft", "Settled", "Written Off"]],
				}
const set_loan_filters = (frm, filters) => {
		frm.set_query("loan", function () {
			return {
				"filters": filters,
			};
		});
}
frappe.ui.form.on('Process Loan Interest Accrual', {
	onload: function (frm) {
		set_loan_filters(frm, active_loan_filters)
	},
	loan_product: function (frm) {
		if (frm.doc.loan_product) {
			let loan_filters = active_loan_filters
			loan_filters["loan_product"] = frm.doc.loan_product
			set_loan_filters(frm, loan_filters)
		}
		else {
			set_loan_filters(frm, active_loan_filters)
		}
	},
});
