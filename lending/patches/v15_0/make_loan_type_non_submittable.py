# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe


def execute():
	lt = frappe.qb.DocType("Loan Product")
	frappe.qb.update(lt).set(lt.docstatus, 0).run()
