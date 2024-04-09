# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, date_diff, flt, get_last_day, getdate

from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
from lending.loan_management.doctype.loan_repayment_schedule.utils import (
	add_single_month,
	get_amounts,
	get_loan_partner_details,
	get_monthly_repayment_amount,
	set_demand,
)


class LoanRepaymentSchedule(Document):
	def validate(self):
		self.set_repayment_period()
		self.validate_repayment_method()
		self.make_customer_repayment_schedule()
		self.make_co_lender_schedule()

	def on_submit(self):
		self.make_bpi_demand()
		self.make_demand_for_advance_payment()

	def make_demand_for_advance_payment(self):
		if self.restructure_type == "Advance Payment":
			advance_payment = ""
			for row in self.repayment_schedule:
				if not row.demand_generated:
					advance_payment = row
					break

			set_demand(advance_payment.name)
			create_loan_demand(
				self.loan,
				self.posting_date,
				"EMI",
				"Interest",
				advance_payment.interest_amount,
				loan_repayment_schedule=self.name,
				loan_disbursement=self.loan_disbursement,
				repayment_schedule_detail=advance_payment.name,
			)

			create_loan_demand(
				self.loan,
				self.posting_date,
				"EMI",
				"Principal",
				advance_payment.principal_amount,
				loan_repayment_schedule=self.name,
				loan_disbursement=self.loan_disbursement,
				repayment_schedule_detail=advance_payment.name,
			)

	def make_bpi_demand(self):
		if self.broken_period_interest > 0 and self.broken_period_interest_days > 0:
			bpi_row = self.repayment_schedule[0]

			set_demand(bpi_row.name)
			create_loan_demand(
				self.loan,
				bpi_row.payment_date,
				"BPI",
				"Interest",
				bpi_row.interest_amount,
				loan_repayment_schedule=self.name,
				loan_disbursement=self.loan_disbursement,
				repayment_schedule_detail=bpi_row.name,
				paid_amount=bpi_row.interest_amount,
			)

	def on_cancel(self):
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		if self.broken_period_interest and self.broken_period_interest > 0:
			bpi_row = self.repayment_schedule[0]
			frappe.db.set_value("Repayment Schedule", bpi_row.name, "demand_generated", 0)
			loan_demand = frappe.get_doc("Loan Demand", {"repayment_schedule_detail": bpi_row.name})
			loan_demand.cancel()

		reverse_loan_interest_accruals(self.loan, self.posting_date, loan_repayment_schedule=self.name)

	def set_repayment_period(self):
		if self.repayment_frequency == "One Time":
			self.repayment_method = "Repay Over Number of Periods"
			self.repayment_periods = 1

	def make_customer_repayment_schedule(self):
		self.set("repayment_schedule", [])

		self.broken_period_interest = 0
		(
			previous_interest_amount,
			balance_amount,
			additional_principal_amount,
			pending_prev_days,
		) = self.add_rows_from_prev_disbursement("repayment_schedule", 100)

		self.make_repayment_schedule(
			"repayment_schedule",
			previous_interest_amount,
			balance_amount,
			additional_principal_amount,
			pending_prev_days,
			100,
		)

	def make_co_lender_schedule(self):
		if not self.loan_partner:
			return

		self.set("colender_schedule", [])

		loan_partner_details = get_loan_partner_details(self.loan_partner)

		if loan_partner_details.repayment_schedule_type == "EMI (PMT) Based":
			partner_loan_amount = (
				self.current_principal_amount * flt(loan_partner_details.partner_loan_share_percentage) / 100
			)
			share_percentage = 100
		elif loan_partner_details.repayment_schedule_type == "Collection at partner's percentage":
			partner_loan_amount = self.current_principal_amount
			share_percentage = flt(loan_partner_details.partner_loan_share_percentage)

		self.make_repayment_schedule("colender_schedule", 0, partner_loan_amount, 0, 0, share_percentage)

	def make_repayment_schedule(
		self,
		schedule_field,
		previous_interest_amount,
		balance_amount,
		additional_principal_amount,
		pending_prev_days,
		share_percentage,
	):
		payment_date = self.repayment_start_date
		carry_forward_interest = self.adjusted_interest
		moratorium_interest = 0

		rate_of_interest = self.get_rate_of_interest(schedule_field)

		if not self.restructure_type:
			monthly_repayment_amount = get_monthly_repayment_amount(
				balance_amount, rate_of_interest, self.repayment_periods, self.repayment_frequency
			)
		else:
			monthly_repayment_amount = self.monthly_repayment_amount

		if self.moratorium_tenure and self.repayment_frequency == "Monthly":
			payment_date = add_months(self.repayment_start_date, -1 * self.moratorium_tenure)
			self.moratorium_end_date = add_months(self.repayment_start_date, -1)

		tenure = self.get_applicable_tenure(payment_date)
		additional_days = cint(self.broken_period_interest_days)

		if len(self.get(schedule_field)) > 0:
			self.broken_period_interest_days = 0

		if additional_days < 0:
			self.broken_period_interest_days = 0

		while balance_amount > 0:
			if self.moratorium_tenure and self.repayment_frequency == "Monthly":
				if getdate(payment_date) > getdate(self.moratorium_end_date):
					if (
						self.moratorium_type == "EMI"
						and self.treatment_of_interest == "Capitalize"
						and moratorium_interest
					):
						balance_amount = self.loan_amount + moratorium_interest
						monthly_repayment_amount = get_monthly_repayment_amount(
							balance_amount, rate_of_interest, self.repayment_periods, self.repayment_frequency
						)
						moratorium_interest = 0

			payment_days, months = self.get_days_and_months(
				payment_date, additional_days, balance_amount, schedule_field, share_percentage
			)

			interest_amount, principal_amount, balance_amount, total_payment, days = get_amounts(
				balance_amount,
				rate_of_interest,
				payment_days,
				months,
				monthly_repayment_amount,
				carry_forward_interest,
				previous_interest_amount,
				additional_principal_amount,
				pending_prev_days,
			)

			if self.moratorium_tenure and self.repayment_frequency == "Monthly":
				if getdate(payment_date) <= getdate(self.moratorium_end_date):
					if self.moratorium_type == "EMI":
						total_payment = 0
					else:
						total_payment = interest_amount

					principal_amount = 0
					balance_amount = self.loan_amount
					moratorium_interest += interest_amount
					interest_amount = 0
				elif (
					self.moratorium_type == "EMI"
					and self.treatment_of_interest == "Add to first repayment"
					and moratorium_interest
				):
					interest_amount += moratorium_interest
					total_payment = principal_amount + interest_amount
					moratorium_interest = 0

			if self.repayment_schedule_type == "Pro-rated calendar months":
				next_payment_date = get_last_day(payment_date)
				if self.repayment_date_on == "Start of the next month":
					next_payment_date = add_days(next_payment_date, 1)

				payment_date = next_payment_date

			self.add_repayment_schedule_row(
				payment_date,
				principal_amount,
				interest_amount,
				total_payment,
				balance_amount,
				days,
				repayment_schedule_field=schedule_field,
				share_percentage=share_percentage,
			)

			if (
				self.repayment_method == "Repay Over Number of Periods"
				and len(self.get(schedule_field)) >= tenure
			):
				self.get(schedule_field)[-1].principal_amount += balance_amount
				self.get(schedule_field)[-1].balance_loan_amount = 0
				self.get(schedule_field)[-1].total_payment = (
					self.get(schedule_field)[-1].interest_amount + self.get(schedule_field)[-1].principal_amount
				)
				balance_amount = 0

			payment_date = self.get_next_payment_date(payment_date)

			carry_forward_interest = 0
			additional_days = 0
			previous_interest_amount = 0
			additional_principal_amount = 0
			pending_prev_days = 0

		if schedule_field == "repayment_schedule" and not self.restructure_type:
			self.monthly_repayment_amount = monthly_repayment_amount

	def get_rate_of_interest(self, schedule_field):
		if schedule_field == "repayment_schedule":
			return self.rate_of_interest
		else:
			return self.loan_partner_rate_of_interest

	def get_next_payment_date(self, payment_date):
		if (
			self.repayment_schedule_type
			in ["Monthly as per repayment start date", "Monthly as per cycle date", "Line of Credit"]
			or self.repayment_date_on == "End of the current month"
		) and self.repayment_frequency == "Monthly":
			next_payment_date = add_single_month(payment_date)
			payment_date = next_payment_date
		elif self.repayment_frequency == "Weekly":
			payment_date = add_days(payment_date, 7)
		elif self.repayment_frequency == "Daily":
			payment_date = add_days(payment_date, 1)
		elif self.repayment_frequency == "Quarterly":
			payment_date = add_months(payment_date, 3)

		return payment_date

	def get_applicable_tenure(self, payment_date):
		loan_status = frappe.db.get_value("Loan", self.loan, "status") or "Sanctioned"

		if self.repayment_frequency == "Monthly" and (
			loan_status == "Sanctioned" or self.repayment_schedule_type == "Line of Credit"
		):
			tenure = self.repayment_periods
			if self.repayment_frequency == "Monthly" and self.moratorium_tenure:
				tenure += cint(self.moratorium_tenure)
		elif loan_status == "Partially Disbursed":
			prev_schedule = frappe.db.get_value(
				"Loan Repayment Schedule", {"loan": self.loan, "docstatus": 1, "status": "Active"}
			)
			tenure = frappe.db.count("Repayment Schedule", {"parent": prev_schedule})
		else:
			tenure = self.repayment_periods

		if self.repayment_frequency == "Monthly" or self.restructure_type == "Pre Payment":
			self.broken_period_interest_days = date_diff(add_months(payment_date, -1), self.posting_date)
			if (
				self.broken_period_interest_days > 0
				and not self.moratorium_tenure
				and loan_status != "Partially Disbursed"
			):
				tenure += 1

		return tenure

	def add_rows_from_prev_disbursement(self, schedule_field, share_percentage):
		previous_interest_amount = 0
		completed_tenure = 0
		balance_principal_amount = self.current_principal_amount
		additional_principal_amount = 0
		pending_prev_days = 0

		loan_status = frappe.db.get_value("Loan", self.loan, "status")
		if (
			loan_status == "Partially Disbursed" and self.repayment_schedule_type != "Line of Credit"
		) or self.restructure_type == "Advance Payment":
			prev_schedule = frappe.get_doc(
				"Loan Repayment Schedule", {"loan": self.loan, "docstatus": 1, "status": "Active"}
			)
			if prev_schedule:
				after_bpi = 0
				prev_repayment_date = prev_schedule.posting_date
				prev_balance_amount = prev_schedule.current_principal_amount
				self.monthly_repayment_amount = prev_schedule.monthly_repayment_amount
				first_date = prev_schedule.get(schedule_field)[0].payment_date

				if getdate(first_date) < prev_schedule.repayment_start_date:
					after_bpi = 1

				if (
					getdate(self.repayment_start_date) > getdate(prev_schedule.repayment_start_date) or after_bpi
				):
					for row in prev_schedule.get(schedule_field):
						if getdate(row.payment_date) < getdate(self.posting_date):
							self.add_repayment_schedule_row(
								row.payment_date,
								row.principal_amount,
								row.interest_amount,
								row.total_payment,
								row.balance_loan_amount,
								row.number_of_days,
								demand_generated=row.demand_generated,
								repayment_schedule_field=schedule_field,
							)
							prev_repayment_date = row.payment_date
							prev_balance_amount = row.balance_loan_amount
							if row.principal_amount:
								completed_tenure += 1
						elif not after_bpi:
							self.repayment_start_date = row.payment_date
							prev_repayment_date = row.payment_date
							break

					if after_bpi and not self.restructure_type:
						self.broken_period_interest = prev_schedule.broken_period_interest

					pending_prev_days = date_diff(self.posting_date, prev_repayment_date)

					if pending_prev_days > 0:
						previous_interest_amount += flt(
							prev_balance_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)
				elif date_diff(add_months(self.repayment_start_date, -1), self.posting_date) > 0:
					self.repayment_start_date = prev_schedule.repayment_start_date
					prev_days = date_diff(self.posting_date, prev_schedule.posting_date)
					interest_amount = flt(prev_balance_amount * flt(self.rate_of_interest) * prev_days / (36500))
					self.broken_period_interest += interest_amount
				else:
					prev_balance_amount = prev_schedule.current_principal_amount
					previous_interest_amount = prev_schedule.get(schedule_field)[0].interest_amount
					additional_principal_amount = self.disbursed_amount

				if self.restructure_type == "Advance Payment":
					paid_principal_amount = prev_balance_amount - self.current_principal_amount
					balance_principal_amount = self.current_principal_amount
					interest_amount = self.monthly_repayment_amount - paid_principal_amount
					previous_interest_amount = 0

					self.repayment_start_date = frappe.db.get_value(
						"Loan Restructure", self.loan_restructure, "repayment_start_date"
					)
					self.add_repayment_schedule_row(
						self.repayment_start_date,
						paid_principal_amount,
						interest_amount,
						self.monthly_repayment_amount,
						balance_principal_amount,
						date_diff(self.repayment_start_date, self.posting_date),
						0,
						repayment_schedule_field=schedule_field,
						share_percentage=share_percentage,
					)

					pending_prev_days = date_diff(self.repayment_start_date, self.posting_date)

					if pending_prev_days > 0:
						previous_interest_amount += flt(
							balance_principal_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)

					self.repayment_start_date = self.get_next_payment_date(self.repayment_start_date)

					completed_tenure += 1
				elif not self.restructure_type:
					self.current_principal_amount = self.disbursed_amount + prev_balance_amount
					balance_principal_amount = self.current_principal_amount

				if self.repayment_method == "Repay Over Number of Periods" and not self.restructure_type:
					self.monthly_repayment_amount = get_monthly_repayment_amount(
						balance_principal_amount,
						self.rate_of_interest,
						self.repayment_periods - completed_tenure,
						self.repayment_frequency,
					)

		return (
			previous_interest_amount,
			balance_principal_amount,
			additional_principal_amount,
			pending_prev_days,
		)

	def validate_repayment_method(self):
		if not self.repayment_start_date:
			frappe.throw(_("Repayment Start Date is mandatory for term loans"))

		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period":
			self.monthly_repayment_amount = frappe.db.get_value(
				"Loan", self.loan, "monthly_repayment_amount"
			)
			if not self.monthly_repayment_amount:
				frappe.throw(_("Please enter repayment Amount"))
			if self.monthly_repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def get_days_and_months(
		self, payment_date, additional_days, balance_amount, schedule_field, share_percentage
	):
		months = 365
		if self.repayment_frequency == "Monthly":
			if self.repayment_schedule_type == "Monthly as per repayment start date":
				days = 1
				months = 12
			else:
				expected_payment_date = get_last_day(payment_date)
				if self.repayment_date_on == "Start of the next month":
					expected_payment_date = add_days(expected_payment_date, 1)

				if self.repayment_schedule_type in ("Monthly as per cycle date", "Line of Credit"):
					days = date_diff(payment_date, add_months(payment_date, -1))
					if additional_days < 0 or (additional_days > 0 and self.moratorium_tenure):
						days = date_diff(payment_date, self.posting_date)
						additional_days = 0

					if additional_days and not self.moratorium_tenure and not self.restructure_type:
						self.add_broken_period_interest(
							balance_amount,
							additional_days,
							payment_date,
							schedule_field,
							share_percentage=share_percentage,
						)
						additional_days = 0

				elif expected_payment_date == payment_date:
					# using 30 days for calculating interest for all full months
					days = 30
				else:
					days = date_diff(get_last_day(payment_date), payment_date)
		else:
			if payment_date == self.repayment_start_date:
				days = date_diff(payment_date, self.posting_date)
			elif self.repayment_frequency == "Weekly":
				days = 7
			elif self.repayment_frequency == "Daily":
				days = 1
			elif self.repayment_frequency == "Quarterly":
				days = 3
			elif self.repayment_frequency == "One Time":
				days = date_diff(self.repayment_start_date, self.posting_date)

		return days, months

	def add_broken_period_interest(
		self, balance_amount, additional_days, payment_date, schedule_field, share_percentage
	):
		interest_amount = flt(
			balance_amount * flt(self.rate_of_interest) * additional_days / (365 * 100)
		)
		self.broken_period_interest += interest_amount

		payment_date = add_months(payment_date, -1)
		self.add_repayment_schedule_row(
			payment_date,
			0,
			self.broken_period_interest,
			self.broken_period_interest,
			balance_amount,
			additional_days,
			repayment_schedule_field=schedule_field,
			share_percentage=share_percentage,
		)

	def add_repayment_schedule_row(
		self,
		payment_date,
		principal_amount,
		interest_amount,
		total_payment,
		balance_loan_amount,
		days,
		demand_generated=0,
		repayment_schedule_field=None,
		share_percentage=100,
	):
		if (
			self.moratorium_type == "EMI"
			and self.moratorium_end_date
			and getdate(payment_date) <= getdate(self.moratorium_end_date)
		):
			demand_generated = 1

		if not repayment_schedule_field:
			repayment_schedule_field = "repayment_schedule"

		interest_amount = interest_amount * share_percentage / 100
		principal_amount = principal_amount * share_percentage / 100
		total_payment = total_payment * share_percentage / 100

		self.append(
			repayment_schedule_field,
			{
				"number_of_days": days,
				"payment_date": payment_date,
				"principal_amount": principal_amount,
				"interest_amount": interest_amount,
				"total_payment": total_payment,
				"balance_loan_amount": balance_loan_amount,
				"demand_generated": demand_generated,
			},
		)
