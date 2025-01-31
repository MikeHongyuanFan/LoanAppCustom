# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.utils import add_days, nowdate

from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	make_accrual_interest_entry_for_loans,
)


class ProcessLoanInterestAccrual(Document):
	def on_submit(self):
		make_accrual_interest_entry_for_loans(
			self.posting_date,
			self.name,
			loan=self.loan,
			loan_product=self.loan_product,
			accrual_type=self.accrual_type,
			accrual_date=self.posting_date,
			company=self.company,
		)


def schedule_accrual():
	posting_date = add_days(nowdate(), -1)
	process_loan_interest_accrual_for_loans(posting_date=posting_date)


def process_loan_interest_accrual_for_loans(
	posting_date=None, loan_product=None, loan=None, accrual_type="Regular", company=None
):
	loan_process = frappe.new_doc("Process Loan Interest Accrual")
	loan_process.posting_date = posting_date or add_days(nowdate(), -1)
	loan_process.loan_product = loan_product
	loan_process.loan = loan
	loan_process.accrual_type = accrual_type
	loan_process.company = company
	loan_process.submit()

	return loan_process.name
