// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// render
frappe.listview_settings['Loan Security Assignment'] = {
	add_fields: ["status"],
	get_indicator: function(doc) {
		var status_color = {
			"Unpledged": "orange",
			"Pledged": "blue",
			"Pledge Requested": "grey",
			"Release Requested": "grey",
			"Released": "green",
			"Repossessed": "red"
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	}
};
