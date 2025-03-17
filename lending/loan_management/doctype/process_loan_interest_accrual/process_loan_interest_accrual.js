// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// frappe.ui.form.on('Process Loan Interest Accrual', {
// 	refresh: function(frm) {

// 	}
// });
frappe.ui.form.on('Process Loan Interest Accrual', {
	onload: function (frm) {
		frm.set_query("loan", function () {
			return {
				"filters": {
					"docstatus": 1,
					"status": ["not in", ["Closed", "Draft", "Settled", "Written Off"]],
				}
			};
		});
	},
});
