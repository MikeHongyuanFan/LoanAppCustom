# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import (
	add_days,
	add_months,
	add_to_date,
	date_diff,
	flt,
	get_datetime,
	getdate,
	nowdate,
)

from erpnext.selling.doctype.customer.test_customer import get_customer_dict
from erpnext.setup.doctype.employee.test_employee import make_employee

from lending.loan_management.doctype.loan.loan import request_loan_closure, unpledge_security
from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	get_disbursal_amount,
)
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
	days_in_year,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	post_bulk_payments,
)
from lending.loan_management.doctype.loan_security_release.loan_security_release import (
	get_pledged_security_qty,
)
from lending.loan_management.doctype.process_loan_classification.process_loan_classification import (
	create_process_loan_classification,
)
from lending.loan_management.doctype.process_loan_demand.process_loan_demand import (
	process_daily_loan_demands,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_loans,
)
from lending.loan_management.doctype.process_loan_security_shortfall.process_loan_security_shortfall import (
	create_process_loan_security_shortfall,
)
from lending.tests.test_utils import (
	add_or_update_loan_charges,
	create_demand_loan,
	create_loan,
	create_loan_accounts,
	create_loan_application,
	create_loan_product,
	create_loan_security,
	create_loan_security_price,
	create_loan_security_type,
	create_loan_with_security,
	create_loan_write_off,
	create_repayment_entry,
	create_secured_demand_loan,
	get_loan_interest_accrual,
	make_loan_disbursement_entry,
	set_loan_accrual_frequency,
	set_loan_settings_in_company,
	setup_loan_demand_offset_order,
)


class TestLoan(IntegrationTestCase):
	def setUp(self):
		set_loan_settings_in_company()
		create_loan_accounts()
		setup_loan_demand_offset_order()

		set_loan_accrual_frequency("Monthly")
		simple_terms_loans = [
			["Personal Loan", 500000, 8.4, "Monthly as per repayment start date"],
			["Term Loan Product 1", 12000, 7.5, "Monthly as per repayment start date"],
		]

		pro_rated_term_loans = [
			["Term Loan Product 2", 12000, 7.5, "Pro-rated calendar months", "Start of the next month"],
			["Term Loan Product 3", 1200, 25, "Pro-rated calendar months", "End of the current month"],
		]

		cyclic_date_term_loans = [
			["Term Loan Product 4", 3000000, 25, "Monthly as per cycle date"],
		]

		loc_loans = [
			["Term Loan Product 5", 3000000, 25, "Line of Credit"],
		]

		for loan_product in simple_terms_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in cyclic_date_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)
			add_or_update_loan_charges(loan_product[0])

		for loan_product in loc_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
			)

		for loan_product in pro_rated_term_loans:
			create_loan_product(
				loan_product[0],
				loan_product[0],
				loan_product[1],
				loan_product[2],
				repayment_schedule_type=loan_product[3],
				repayment_date_on=loan_product[4],
			)

		create_loan_product(
			"Stock Loan",
			"Stock Loan",
			2000000,
			13.5,
			25,
			1,
			5,
			repayment_schedule_type="Monthly as per repayment start date",
			collection_offset_sequence_for_standard_asset="Test EMI Based Standard Loan Demand Offset Order",
		)

		create_loan_product(
			"Demand Loan",
			"Demand Loan",
			2000000,
			13.5,
			25,
			0,
			5,
			collection_offset_sequence_for_standard_asset="Test Demand Loan Loan Demand Offset Order",
			collection_offset_sequence_for_sub_standard_asset=None,
			collection_offset_sequence_for_written_off_asset=None,
			collection_offset_sequence_for_settlement_collection=None,
		)

		create_loan_security_type()
		create_loan_security()

		create_loan_security_price(
			"Test Security 1", 500, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)
		create_loan_security_price(
			"Test Security 2", 250, "Nos", get_datetime(), get_datetime(add_to_date(nowdate(), hours=24))
		)

		self.applicant1 = make_employee("robert_loan@loan.com")
		if not frappe.db.exists("Customer", "_Test Loan Customer"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer")).insert(ignore_permissions=True)

		if not frappe.db.exists("Customer", "_Test Loan Customer 1"):
			frappe.get_doc(get_customer_dict("_Test Loan Customer 1")).insert(ignore_permissions=True)

		self.applicant2 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer"}, "name")
		self.applicant3 = frappe.db.get_value("Customer", {"name": "_Test Loan Customer 1"}, "name")

		frappe.db.set_value(
			"Loan Product", "Demand Loan", "customer_refund_account", "Customer Refund Account - _TC"
		)

	def test_loan_with_repayment_periods(self):
		posting_date = "2025-01-27"
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			repayment_periods=20,
			repayment_start_date=add_months(posting_date, 1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			280000,
			repayment_start_date=add_months(posting_date, 1),
			disbursement_date=posting_date,
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		schedule = loan_repayment_schedule.repayment_schedule

		loan.load_from_db()
		self.assertEqual(loan_repayment_schedule.monthly_repayment_amount, 15052)
		self.assertEqual(flt(loan.total_interest_payable, 0), 20970)
		self.assertEqual(flt(loan.total_payment, 0), 300970)
		self.assertEqual(len(schedule), 20)

		for idx, principal_amount, interest_amount, balance_loan_amount in [
			[3, 13392, 1660, 226979],
			[19, 14875, 106, 0],
			[17, 14745, 307, 29715],
		]:
			self.assertEqual(flt(schedule[idx].principal_amount, 0), principal_amount)
			self.assertEqual(flt(schedule[idx].interest_amount, 0), interest_amount)
			self.assertEqual(flt(schedule[idx].balance_loan_amount, 0), balance_loan_amount)

	def test_loan_with_fixed_amount_per_period(self):
		disbursement_date = "2020-10-01"
		loan = create_loan(
			self.applicant1,
			"Personal Loan",
			280000,
			"Repay Over Number of Periods",
			repayment_periods=20,
			repayment_start_date=add_months(disbursement_date, 1),
		)

		loan.repayment_method = "Repay Fixed Amount per Period"
		loan.monthly_repayment_amount = 14000
		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			280000,
			repayment_start_date=add_months(disbursement_date, 1),
			disbursement_date=disbursement_date,
		)

		loan_repayment_schedule = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)

		loan.load_from_db()
		self.assertEqual(len(loan_repayment_schedule.repayment_schedule), 22)
		self.assertEqual(flt(loan.total_interest_payable, 0), 22708)
		self.assertEqual(flt(loan.total_payment, 0), 302708)

	def test_loan_with_security(self):
		pledge = [
			{
				"loan_security": "Test Security 1",
				"qty": 4000.00,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

	def test_loan_disbursement(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledge, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		self.assertEqual(loan.loan_amount, 1000000)

		loan.submit()

		loan_disbursement_entry1 = make_loan_disbursement_entry(loan.name, 500000)
		loan_disbursement_entry2 = make_loan_disbursement_entry(loan.name, 500000)

		loan = frappe.get_doc("Loan", loan.name)
		gl_entries1 = frappe.db.get_all(
			"GL Entry",
			fields=["name"],
			filters={"voucher_type": "Loan Disbursement", "voucher_no": loan_disbursement_entry1.name},
		)

		gl_entries2 = frappe.db.get_all(
			"GL Entry",
			fields=["name"],
			filters={"voucher_type": "Loan Disbursement", "voucher_no": loan_disbursement_entry2.name},
		)

		self.assertEqual(loan.status, "Disbursed")
		self.assertEqual(loan.disbursed_amount, 1000000)
		self.assertTrue(gl_entries1)
		self.assertTrue(gl_entries2)

	def test_sanctioned_amount_limit(self):
		# Clear loan docs before checking
		frappe.db.sql("DELETE FROM `tabLoan` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql("DELETE FROM `tabLoan Application` where applicant = '_Test Loan Customer 1'")
		frappe.db.sql(
			"DELETE FROM `tabLoan Security Assignment` where applicant = '_Test Loan Customer 1'"
		)

		if not frappe.db.get_value(
			"Sanctioned Loan Amount",
			filters={
				"applicant_type": "Customer",
				"applicant": "_Test Loan Customer 1",
				"company": "_Test Company",
			},
		):
			frappe.get_doc(
				{
					"doctype": "Sanctioned Loan Amount",
					"applicant_type": "Customer",
					"applicant": "_Test Loan Customer 1",
					"sanctioned_amount_limit": 1500000,
					"company": "_Test Company",
				}
			).insert(ignore_permissions=True)

		# Make First Loan
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)
		loan = create_demand_loan(
			self.applicant3, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		# Make second loan greater than the sanctioned amount
		loan_application = create_loan_application(
			"_Test Company", self.applicant3, "Demand Loan", pledge, do_not_save=True
		)
		self.assertRaises(frappe.ValidationError, loan_application.save)

	def test_loan_closure(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)
		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		# Adding 5 since repayment is made 5 days late after due date
		# and since payment type is loan closure so interest should be considered for those
		# 5 days as well though in grace period

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * 34) / (36500)
		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=add_days(last_date, 4), loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=add_days(last_date, 5), loan=loan.name)
		repayment_entry = create_repayment_entry(
			loan.name,
			add_days(last_date, 5),
			flt(loan.loan_amount + accrued_interest_amount),
		)

		repayment_entry.submit()

		amounts = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "Normal", "demand_subtype": "Interest"},
			["SUM(demand_amount) as payable_amount"],
		)

		self.assertEqual(flt(amounts[0].payable_amount, 0), flt(accrued_interest_amount, 0))
		self.assertEqual(flt(repayment_entry.penalty_amount, 5), 0)

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

	def test_loan_repayment_for_term_loan(self):
		pledges = [
			{"loan_security": "Test Security 2", "qty": 4000.00},
			{"loan_security": "Test Security 1", "qty": 2000.00},
		]
		posting_date = "2025-01-30"
		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)
		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2,
			"Stock Loan",
			"Repay Over Number of Periods",
			12,
			loan_application,
			posting_date=add_months(posting_date, -1),
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			loan.loan_amount,
			disbursement_date=add_months(posting_date, -1),
			repayment_start_date=posting_date,
		)

		process_daily_loan_demands(loan=loan.name, posting_date=posting_date)

		repayment_entry = create_repayment_entry(loan.name, posting_date, 89768.75)

		repayment_entry.submit()

		# amounts = frappe.db.get_value(
		# 	"Loan Interest Accrual", {"loan": loan.name}, ["paid_interest_amount", "paid_principal_amount"]
		# )

		amounts = frappe.db.get_all(
			"Loan Demand",
			{"loan": loan.name, "demand_type": "EMI", "demand_subtype": "Interest"},
			["SUM(paid_amount) as paid_amount"],
		)

		self.assertEqual(flt(amounts[0].paid_amount, 2), 11465.75)
		self.assertEqual(flt(repayment_entry.principal_amount_paid, 2), 78303.00)

	def test_security_shortfall(self):
		frappe.db.sql(
			"""UPDATE `tabLoan Security Price` SET loan_security_price = 250
			where loan_security='Test Security 2'"""
		)
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		make_loan_disbursement_entry(loan.name, loan.loan_amount)

		frappe.db.sql(
			"""UPDATE `tabLoan Security Price` SET loan_security_price = 100
			where loan_security='Test Security 2'"""
		)

		create_process_loan_security_shortfall()
		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertTrue(loan_security_shortfall)

		self.assertEqual(flt(loan_security_shortfall.loan_amount, 2), 1000000.00)
		self.assertEqual(flt(loan_security_shortfall.security_value, 2), 800000.00)
		self.assertEqual(flt(loan_security_shortfall.shortfall_amount, 2), 600000.00)

		frappe.db.sql(
			""" UPDATE `tabLoan Security Price` SET loan_security_price = 250
			where loan_security='Test Security 2'"""
		)

		create_process_loan_security_shortfall()
		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertEqual(loan_security_shortfall.status, "Completed")
		self.assertEqual(loan_security_shortfall.shortfall_amount, 0)

	def test_loan_security_release(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=last_date, loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=last_date, loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name,
			last_date,
			flt(loan.loan_amount + accrued_interest_amount),
		)
		repayment_entry.submit()

		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

		unpledge_request = unpledge_security(loan=loan.name, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		loan.load_from_db()

		pledged_qty = get_pledged_security_qty(loan.name)

		self.assertEqual(loan.status, "Closed")
		self.assertEqual(sum(pledged_qty.values()), 0)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))

		self.assertEqual(amounts["pending_principal_amount"], 0)
		self.assertEqual(amounts["payable_principal_amount"], 0.0)
		self.assertEqual(amounts["interest_amount"], 0)

	def test_partial_loan_security_release(self):
		pledge = [
			{"loan_security": "Test Security 1", "qty": 2000.00},
			{"loan_security": "Test Security 2", "qty": 4000.00},
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(posting_date=last_date, company="_Test Company")

		repayment_entry = create_repayment_entry(loan.name, add_days(last_date, 5), 600000)
		repayment_entry.submit()

		unpledge_map = {"Test Security 2": 2000}

		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()
		unpledge_request.load_from_db()
		self.assertEqual(unpledge_request.docstatus, 1)

	def test_sanctioned_loan_security_release(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		unpledge_map = {"Test Security 1": 4000}
		unpledge_request = unpledge_security(loan=loan.name, security_map=unpledge_map, save=1)
		unpledge_request.submit()
		unpledge_request.status = "Approved"
		unpledge_request.save()
		unpledge_request.submit()

	def test_disbursal_check_with_shortfall(self):
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		# Disbursing 7,00,000 from the allowed 10,00,000 according to security pledge
		make_loan_disbursement_entry(loan.name, 700000)

		frappe.db.sql(
			"""UPDATE `tabLoan Security Price` SET loan_security_price = 100
			where loan_security='Test Security 2'"""
		)

		create_process_loan_security_shortfall()
		loan_security_shortfall = frappe.get_doc("Loan Security Shortfall", {"loan": loan.name})
		self.assertTrue(loan_security_shortfall)

		self.assertEqual(get_disbursal_amount(loan.name), 0)

		frappe.db.sql(
			""" UPDATE `tabLoan Security Price` SET loan_security_price = 250
			where loan_security='Test Security 2'"""
		)

	def test_disbursal_check_without_shortfall(self):
		pledges = [
			{
				"loan_security": "Test Security 2",
				"qty": 8000.00,
				"haircut": 50,
			}
		]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Stock Loan", pledges, "Repay Over Number of Periods", 12
		)

		create_loan_security_assignment(loan_application)

		loan = create_loan_with_security(
			self.applicant2, "Stock Loan", "Repay Over Number of Periods", 12, loan_application
		)
		loan.submit()

		# Disbursing 7,00,000 from the allowed 10,00,000 according to security pledge
		make_loan_disbursement_entry(loan.name, 700000)

		self.assertEqual(get_disbursal_amount(loan.name), (300000, 700000))

	def test_pending_loan_amount_after_closure_request(self):
		pledge = [{"loan_security": "Test Security 1", "qty": 4000.00}]

		loan_application = create_loan_application(
			"_Test Company", self.applicant2, "Demand Loan", pledge
		)
		create_loan_security_assignment(loan_application)

		loan = create_demand_loan(
			self.applicant2, "Demand Loan", loan_application, posting_date="2019-10-01"
		)
		loan.submit()

		self.assertEqual(loan.loan_amount, 1000000)

		first_date = "2019-10-01"
		last_date = "2019-10-30"

		no_of_days = date_diff(last_date, first_date) + 1

		no_of_days += 5

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * no_of_days) / (
			days_in_year(get_datetime(first_date).year) * 100
		)

		make_loan_disbursement_entry(loan.name, loan.loan_amount, disbursement_date=first_date)
		process_loan_interest_accrual_for_loans(
			posting_date=last_date, loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date=last_date, loan=loan.name)

		amounts = calculate_amounts(loan.name, add_days(last_date, 5), payment_type="Loan Closure")

		repayment_entry = create_repayment_entry(
			loan.name, add_days(last_date, 5), amounts["payable_amount"]
		)
		repayment_entry.submit()
		request_loan_closure(loan.name)
		loan.load_from_db()
		self.assertEqual(loan.status, "Loan Closure Requested")

		amounts = calculate_amounts(loan.name, add_days(last_date, 5))
		self.assertEqual(amounts["pending_principal_amount"], 0.0)

	def test_penalty(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
			penalty_charges_rate=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-07-07", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-07-06", loan=loan.name, company="_Test Company"
		)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-07-07")
		self.assertEqual(flt(amounts["penalty_amount"], 2), 3059.7)

	def test_same_date_for_daily_accruals(self):
		set_loan_accrual_frequency("Daily")
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
			penalty_charges_rate=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-07-07", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-07-06", loan=loan.name, company="_Test Company"
		)

		amounts = calculate_amounts(against_loan=loan.name, posting_date="2024-07-07")

		self.assertEqual(flt(amounts["penalty_amount"], 2), 3059.70)

		accruals = frappe.get_all(
			"Loan Interest Accrual",
			{"loan": loan.name, "accrual_type": "Normal Interest"},
			["start_date", "posting_date"],
		)
		for i in accruals:
			self.assertEqual(i.start_date, i.posting_date)

	def test_loan_write_off_limit(self):
		loan = create_secured_demand_loan(self.applicant2)
		self.assertEqual(loan.loan_amount, 1000000)
		repayment_date = "2019-11-01"

		accrued_interest_amount = (loan.loan_amount * loan.rate_of_interest * 31) / (36500)
		process_loan_interest_accrual_for_loans(
			posting_date=add_days("2019-11-01", -1), loan=loan.name, company="_Test Company"
		)
		process_daily_loan_demands(posting_date="2019-11-01", loan=loan.name)
		# repay 50 less so that it can be automatically written off
		repayment_entry = create_repayment_entry(
			loan.name,
			repayment_date,
			flt(loan.loan_amount + accrued_interest_amount - 50),
		)

		repayment_entry.submit()

		# -50 because shortfall_amount
		self.assertEqual(flt(repayment_entry.excess_amount, 0), -50)
		interest_waiver_account = frappe.db.get_value(
			"Loan Product", "Demand Loan", "interest_waiver_account"
		)
		gl_data = frappe.db.get_value(
			"GL Entry",
			{
				"voucher_no": repayment_entry.name,
				"voucher_type": "Loan Repayment",
				"account": interest_waiver_account,
			},
			["debit", "credit"],
			as_dict=1,
		)
		self.assertEqual(flt(gl_data.debit, 0), 50)
		self.assertEqual(flt(gl_data.credit, 0), 0)

	def test_loan_repayment_against_partially_disbursed_loan(self):
		loan = create_secured_demand_loan(self.applicant2, disbursement_amount=500000)
		loan.load_from_db()

		self.assertEqual(loan.status, "Partially Disbursed")
		create_repayment_entry(loan.name, add_days("2019-10-30", 5), flt(loan.loan_amount / 3))

	def test_term_loan_schedule_types(self):
		def _create_loan_for_schedule(loan_product, repayment_method, monthly_repayment_amount=None):
			loan = create_loan(
				self.applicant1,
				loan_product,
				12000,
				repayment_method,
				12,
				repayment_start_date="2022-10-17",
				monthly_repayment_amount=monthly_repayment_amount,
			)

			loan.posting_date = "2022-10-17"
			loan.submit()
			make_loan_disbursement_entry(
				loan.name,
				loan.loan_amount,
				disbursement_date=loan.posting_date,
				repayment_start_date="2022-10-17",
			)

			loan_repayment_schedule = frappe.get_doc("Loan Repayment Schedule", {"loan": loan.name})
			schedule = loan_repayment_schedule.repayment_schedule

			return schedule

		schedule = _create_loan_for_schedule("Term Loan Product 1", "Repay Over Number of Periods")

		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-17"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-17"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-17"))

		schedule = _create_loan_for_schedule("Term Loan Product 2", "Repay Over Number of Periods")
		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-11-01"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-12-01"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-10-01"))

		schedule = _create_loan_for_schedule("Term Loan Product 3", "Repay Over Number of Periods")
		# Check for first, second and last installment date
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-31"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-30"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-30"))

		schedule = _create_loan_for_schedule("Term Loan Product 3", "Repay Over Number of Periods")
		self.assertEqual(schedule[0].payment_date, getdate("2022-10-31"))
		self.assertEqual(schedule[1].payment_date, getdate("2022-11-30"))
		self.assertEqual(schedule[-1].payment_date, getdate("2023-09-30"))

	def test_advance_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-01",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-04-01", repayment_start_date="2024-05-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 47523)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-29", 47523, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		lrs = frappe.get_doc(
			"Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"}
		)
		self.assertEqual(lrs.monthly_repayment_amount, 47523)
		self.assertEqual(lrs.get("repayment_schedule")[3].total_payment, 47523)
		self.assertEqual(lrs.broken_period_interest, 0)
		self.assertEqual(lrs.broken_period_interest_days, 0)

	def test_multi_tranche_disbursement_accrual(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1000000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-05-05",
			posting_date="2024-04-18",
			rate_of_interest=23,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name,
			500000,
			disbursement_date=getdate("2024-04-18"),
			repayment_start_date=getdate("2024-05-05"),
		)

		make_loan_disbursement_entry(
			loan.name,
			300000,
			disbursement_date=getdate("2024-05-10"),
			repayment_start_date=getdate("2024-06-05"),
		)

		make_loan_disbursement_entry(
			loan.name,
			200000,
			disbursement_date=getdate("2024-06-10"),
			repayment_start_date=getdate("2024-07-05"),
		)

	def test_hybrid_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-01",
			rate_of_interest=28,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-01", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 8253)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-29", 50000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		repayment_entry.load_from_db()

		self.assertEqual(len(repayment_entry.get("repayment_details")), 2)

	def test_multiple_advance_payment(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1200000,
			"Repay Over Number of Periods",
			36,
			repayment_start_date="2024-06-05",
			posting_date="2024-05-03",
			rate_of_interest=29,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-05-03", repayment_start_date="2024-06-05"
		)
		process_daily_loan_demands(posting_date="2024-06-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(loan.name, "2024-06-05", 50287)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-18", 50287, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-12-05", 251435)
		repayment_entry.submit()

		repayment_entry1 = create_repayment_entry(
			loan.name, "2024-12-21 00:00:00", 150287, repayment_type="Pre Payment"
		)
		repayment_entry1.submit()

		repayment_entry2 = create_repayment_entry(
			loan.name, "2024-12-21 00:00:20", 150287, repayment_type="Pre Payment"
		)
		repayment_entry2.submit()

		# Cancel the entry to check if correct schedule becomes active
		repayment_entry2.cancel()

		# Check only the demands related to repayment_entry1 are only cancelled
		loan_restructure = frappe.db.get_value(
			"Loan Restructure", {"loan_repayment": repayment_entry2.name}
		)
		loan_repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": loan_restructure}
		)
		loan_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan_repayment_schedule": loan_repayment_schedule, "docstatus": 1},
		)
		self.assertFalse(loan_demands)

		# Check only the demands related to repayment_entry1 are only cancelled
		loan_restructure = frappe.db.get_value(
			"Loan Restructure", {"loan_repayment": repayment_entry1.name}
		)
		loan_repayment_schedule = frappe.db.get_value(
			"Loan Repayment Schedule", {"loan_restructure": loan_restructure}
		)
		loan_demands = frappe.db.get_all(
			"Loan Demand",
			{"loan_repayment_schedule": loan_repayment_schedule, "docstatus": 1},
		)
		self.assertTrue(loan_demands)

	def test_future_demand_cancellation(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1200000,
			"Repay Over Number of Periods",
			36,
			repayment_start_date="2024-06-05",
			posting_date="2024-05-03",
			rate_of_interest=29,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-05-03", repayment_start_date="2024-06-05"
		)
		process_daily_loan_demands(posting_date="2024-06-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(
			loan.name, "2024-06-04", 50287, repayment_type="Advance Payment"
		)
		repayment_entry.submit()

		demands = frappe.db.get_all(
			"Loan Demand", {"loan": loan.name, "docstatus": 2, "demand_date": (">", "2024-06-04")}
		)
		self.assertTrue(demands)

	def test_interest_accrual_and_demand_on_freeze_and_unfreeze(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		loan.load_from_db()
		loan.freeze_account = 1
		loan.freeze_date = "2024-11-10"
		loan.save()

		loan.freeze_account = 0
		loan.save()

	def test_loan_write_off_recovery(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		repayment = create_repayment_entry(
			loan.name, "2024-12-05", 1000000, repayment_type="Write Off Recovery"
		)
		repayment.submit()

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Written Off")

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={"voucher_no": repayment.name},
			fields=["account", "debit", "credit"],
		)

		expected_entries = [
			{"account": "Payment Account - _TC", "debit": 1000000, "credit": 0},
			{"account": "Write Off Recovery - _TC", "debit": 0, "credit": 1000000},
		]

		for expected in expected_entries:
			self.assertIn(expected, gl_entries, f"Missing GL entry: {expected}")

	def test_loan_write_off_settlement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2500000,
			"Repay Over Number of Periods",
			24,
			"Customer",
			repayment_start_date="2024-11-05",
			posting_date="2024-10-05",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-10-05", repayment_start_date="2024-11-05"
		)
		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		create_loan_write_off(loan.name, "2024-11-05", write_off_amount=250000)

		repayment = create_repayment_entry(
			loan.name, "2025-01-05", 1500000, repayment_type="Write Off Settlement"
		)
		repayment.submit()

		loan_status = frappe.db.get_value("Loan", loan.name, "status")
		self.assertEqual(loan_status, "Settled")

		gl_entries = frappe.db.get_all(
			"GL Entry",
			filters={"voucher_no": repayment.name},
			fields=["account", "debit", "credit"],
		)

		expected_entries = [
			{"account": "Payment Account - _TC", "debit": 1500000, "credit": 0},
			{"account": "Write Off Recovery - _TC", "debit": 0, "credit": 1500000},
		]

		for expected in expected_entries:
			self.assertIn(expected, gl_entries, f"Missing GL entry: {expected}")

	def test_interest_accrual_overlap(self):
		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			1500000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2025-01-05",
			posting_date="2024-11-28",
			rate_of_interest=28,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-28", repayment_start_date="2025-01-05"
		)

		# Process Loan Interest Accrual
		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-03", loan=loan.name, company="_Test Company"
		)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-04", loan=loan.name, company="_Test Company"
		)
		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-05", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment = create_repayment_entry(loan.name, "2024-12-05", 1150, repayment_type="Pre Payment")

		repayment.submit()
		process_loan_interest_accrual_for_loans(
			posting_date="2024-12-08", loan=loan.name, company="_Test Company"
		)

		process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)
		process_loan_interest_accrual_for_loans(
			posting_date="2025-01-10", loan=loan.name, company="_Test Company"
		)

		repayment = create_repayment_entry(loan.name, "2025-01-03", 10000, repayment_type="Pre Payment")

		repayment.submit()

	def test_principal_amount_paid(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		# Make a scheduled loan repayment
		repayment_entry = create_repayment_entry(
			loan.name, "2024-04-05", 60000, repayment_type="Pre Payment"
		)

		repayment_entry.submit()
		repayment_entry.load_from_db()

		self.assertEqual(flt(repayment_entry.principal_amount_paid, 1), flt(51095.9, 1))

	def test_additional_interest(self):
		frappe.db.set_value(
			"Company",
			"_Test Company",
			"collection_offset_sequence_for_standard_asset",
			"Test EMI Based Standard Loan Demand Offset Order",
		)

		loan = create_loan(
			self.applicant1,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		# Process Loan Interest Accrual
		process_loan_interest_accrual_for_loans(
			posting_date="2024-05-10", loan=loan.name, company="_Test Company"
		)

	def test_npa_loan(self):
		loan = create_loan(
			self.applicant2,
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		process_loan_interest_accrual_for_loans(
			posting_date="2024-04-10", loan=loan.name, company="_Test Company"
		)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		create_process_loan_classification(posting_date="2024-11-05", loan=loan.name)

		# repayment_entry = create_repayment_entry(loan.name, "2024-10-05", 47523)
		# repayment_entry.submit()

	def test_npa_for_loc(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			500000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2024-12-05",
		)

		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)

		# Test Limit Update
		loan.load_from_db()
		self.assertEqual(loan.utilized_limit_amount, 500000)
		self.assertEqual(loan.available_limit_amount, 0)

		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-05", 47523, loan_disbursement=disbursement.name
		)
		repayment_entry.submit()

		loan.load_from_db()

		self.assertEqual(loan.utilized_limit_amount, 500000 - repayment_entry.principal_amount_paid)
		self.assertEqual(loan.available_limit_amount, repayment_entry.principal_amount_paid)

	def test_shortfall_loan_close_limit(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			2,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-04-05", 257840)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-05-05", 257320.97)
		repayment_entry.submit()

	def test_excess_loan_close_limit(self):
		frappe.db.set_value(
			"Loan Product",
			"Term Loan Product 4",
			"customer_refund_account",
			"Customer Refund Account - _TC",
		)
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			500000,
			"Repay Over Number of Periods",
			2,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-06",
			rate_of_interest=25,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-06", repayment_start_date="2024-04-05"
		)
		process_daily_loan_demands(posting_date="2024-05-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-04-05", 257840)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-05-05", 257950.97, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

	def test_full_settlement(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-08-05",
			posting_date="2024-07-05",
			rate_of_interest=22,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)
		repayment_entry = create_repayment_entry(
			loan.name, "2024-08-05", 1000000, repayment_type="Full Settlement"
		)
		repayment_entry.submit()
		loan.load_from_db()
		self.assertEqual(loan.status, "Settled")

	def test_cancellation_of_resulting_repayments_after_cancelling_full_settlements(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			2000000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-08-05",
			posting_date="2024-07-05",
			rate_of_interest=22,
			applicant_type="Customer",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-07-05", repayment_start_date="2024-08-05"
		)

		process_daily_loan_demands(posting_date="2024-09-05", loan=loan.name)
		repayment_entry = create_repayment_entry(
			loan.name, "2024-08-05", 100000, repayment_type="Full Settlement"
		)
		repayment_entry.submit()
		repayment_entry.cancel()
		closed_docs = frappe.db.get_all(
			"Loan Repayment",
			{
				"posting_date": (">=", repayment_entry.posting_date),
				"against_loan": repayment_entry.against_loan,
				"repayment_type": (
					"in",
					[
						"Interest Waiver",
						"Penalty Waiver",
						"Charges Waiver",
					],
				),
			},
			"docstatus",
			order_by="posting_date",
		)
		for closed_doc in closed_docs:
			self.assertEqual(2, closed_doc.docstatus)

	def test_cancellation_of_resulting_repayments_after_cancelling_full_settlements_for_loc(self):
		# makes two disbursements and corresponding full settlements and cancels one of them
		# checks if only the waivers for the cancelled full settlement are cancelled

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			100000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-10-10",
			posting_date="2024-10-01",
			rate_of_interest=20,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2025-12-05",
		)
		loan.submit()

		disbursement_1 = make_loan_disbursement_entry(
			loan.name, 60000, disbursement_date="2024-10-01", repayment_start_date="2024-10-10"
		)

		process_daily_loan_demands(posting_date="2024-10-10", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-10", 10000, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-18", 10000, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		disbursement_2 = make_loan_disbursement_entry(
			loan.name, 40000, disbursement_date="2024-10-05", repayment_start_date="2024-10-15"
		)

		process_daily_loan_demands(posting_date="2024-10-15", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-15", 7000, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-25", 61, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-10-25",
			4000,
			repayment_type="Full Settlement",
			loan_disbursement=disbursement_1.name,
		)
		repayment_entry.submit()
		repayment_entry.cancel()

		repayment_entry = create_repayment_entry(
			loan.name,
			"2024-10-25",
			4000,
			repayment_type="Full Settlement",
			loan_disbursement=disbursement_2.name,
		)
		repayment_entry.submit()

		docs = frappe.db.get_all(
			"Loan Repayment",
			{
				"posting_date": (">=", repayment_entry.posting_date),
				"against_loan": repayment_entry.against_loan,
				"repayment_type": (
					"in",
					[
						"Interest Waiver",
						"Penalty Waiver",
						"Charges Waiver",
					],
				),
			},
			["docstatus", "loan_disbursement"],
			order_by="posting_date",
		)
		for doc in docs:
			if doc.loan_disbursement == disbursement_1.name:
				self.assertEqual(2, doc.docstatus)
			else:
				self.assertEqual(1, doc.docstatus)

	def test_backdated_pre_payment(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 2",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
			moratorium_tenure=1,
			moratorium_type="Principal",
		)

		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-25", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-11-01", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-11-16", 138.90, repayment_type="Normal Repayment"
		)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-12-01", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-11-26", 15000, repayment_type="Pre Payment"
		)
		repayment_entry.submit()

	def test_excess_amount_for_waiver(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			6,
			"Customer",
			"2024-07-15",
			"2024-06-25",
			10,
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-06-25", repayment_start_date="2024-07-15"
		)
		process_daily_loan_demands(posting_date="2025-01-05", loan=loan.name)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2025-01-15",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 5000}],
			}
		)
		sales_invoice.submit()

		repayment_entry = create_repayment_entry(
			loan.name, get_datetime("2025-01-16 00:03:10"), 106684.69
		)
		repayment_entry.submit()

		loan_adjustment = frappe.get_doc(
			{
				"doctype": "Loan Adjustment",
				"loan": loan.name,
				"posting_date": get_datetime("2025-01-16 00:06:10"),
				"adjustments": [{"loan_repayment_type": "Charges Waiver", "amount": 4900}],
			}
		)
		loan_adjustment.submit()

		credit_notes = frappe.get_all(
			"Sales Invoice",
			filters={"loan": loan.name, "is_return": 1, "status": "Return"},
			fields=["name", "grand_total", "return_against"],
		)

		original_invoice_total = frappe.db.get_value("Sales Invoice", sales_invoice.name, "grand_total")

		total_credit_note_sum = sum(abs(flt(cr["grand_total"])) for cr in credit_notes)

		if total_credit_note_sum < original_invoice_total:
			missing_amount = original_invoice_total - total_credit_note_sum
			self.assertTrue(
				total_credit_note_sum >= original_invoice_total,
				f"Credit notes missing amount: {missing_amount}.",
			)

		outstanding_demand = frappe.db.get_value(
			"Loan Demand", {"loan": loan.name, "outstanding_amount": (">", 0)}, "outstanding_amount"
		)
		self.assertEqual(
			flt(outstanding_demand), 0, "There are still outstanding amounts in the loan demand."
		)

	def test_dpd_calculation(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2024-10-05",
			posting_date="2024-09-15",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-15", repayment_start_date="2024-10-05"
		)
		process_daily_loan_demands(posting_date="2024-10-05", loan=loan.name)

		for date in ["2024-10-05", "2024-10-06", "2024-10-07", "2024-10-08", "2024-10-09", "2024-10-10"]:
			create_process_loan_classification(posting_date=date, loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-10-05", 3000)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-10-09", 782)
		repayment_entry.submit()

		process_daily_loan_demands(posting_date="2024-11-05", loan=loan.name)

		repayment_entry = create_repayment_entry(loan.name, "2024-11-05", 3000)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(loan.name, "2024-11-10", 782)
		repayment_entry.submit()

		frappe.db.sql(
			"""
		update `tabDays Past Due Log` set days_past_due = -1 where loan = %s """,
			loan.name,
		)

		create_process_loan_classification(posting_date="2024-10-05", loan=loan.name)

		dpd_logs = frappe.db.sql(
			"""
			SELECT posting_date, days_past_due
			FROM `tabDays Past Due Log`
			WHERE loan = %s
			ORDER BY posting_date
			""",
			(loan.name),
			as_dict=1,
		)

		expected_dpd_values = {
			"2024-10-05": 1,
			"2024-10-06": 2,
			"2024-10-07": 3,
			"2024-10-08": 4,
			"2024-10-09": 0,  # Fully repaid
			"2024-10-10": 0,
			"2024-11-04": 0,
			"2024-11-05": 1,  # DPD starts again after repayment
			"2024-11-06": 2,
			"2024-11-07": 3,
			"2024-11-08": 4,
			"2024-11-09": 5,
			"2024-11-10": 0,  # Fully repaid
		}

		for log in dpd_logs:
			posting_date = log["posting_date"]
			dpd_value = log["days_past_due"]

			posting_date_str = posting_date.strftime("%Y-%m-%d")

			expected_dpd = expected_dpd_values.get(posting_date_str, 0)
			self.assertEqual(
				dpd_value,
				expected_dpd,
				f"DPD mismatch for {posting_date}: Expected {expected_dpd}, got {dpd_value}",
			)

	def test_dpd_calculation_for_loc_loan(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			100000,
			"Repay Over Number of Periods",
			6,
			repayment_start_date="2024-10-10",
			posting_date="2024-10-01",
			rate_of_interest=20,
			applicant_type="Customer",
			limit_applicable_start="2024-01-05",
			limit_applicable_end="2025-12-05",
		)
		loan.submit()

		disbursement_1 = make_loan_disbursement_entry(
			loan.name, 60000, disbursement_date="2024-10-01", repayment_start_date="2024-10-10"
		)

		process_daily_loan_demands(posting_date="2024-10-10", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-10", 10000, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-18", 592, loan_disbursement=disbursement_1.name
		)
		repayment_entry.submit()

		disbursement_2 = make_loan_disbursement_entry(
			loan.name, 40000, disbursement_date="2024-10-05", repayment_start_date="2024-10-15"
		)

		process_daily_loan_demands(posting_date="2024-10-15", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-15", 7000, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		repayment_entry = create_repayment_entry(
			loan.name, "2024-10-25", 61, loan_disbursement=disbursement_2.name
		)
		repayment_entry.submit()

		frappe.db.sql(
			"""
		update `tabDays Past Due Log` set days_past_due = -1 where loan = %s """,
			loan.name,
		)

		create_process_loan_classification(
			posting_date="2024-10-10", loan=loan.name, loan_disbursement=disbursement_1.name
		)
		create_process_loan_classification(
			posting_date="2024-10-15", loan=loan.name, loan_disbursement=disbursement_2.name
		)

		dpd_logs = frappe.db.sql(
			"""
			SELECT posting_date, loan_disbursement, days_past_due
			FROM `tabDays Past Due Log`
			WHERE loan = %s
			ORDER BY posting_date
			""",
			(loan.name,),
			as_dict=1,
		)

		expected_dpd_values = {
			("2024-10-15", disbursement_1.name): 6,
			("2024-10-24", disbursement_2.name): 10,
		}

		for log in dpd_logs:
			posting_date = log["posting_date"].strftime("%Y-%m-%d")
			disbursement = log["loan_disbursement"]
			dpd_value = log["days_past_due"]

			if (posting_date, disbursement) not in expected_dpd_values:
				continue

			expected_dpd = expected_dpd_values[(posting_date, disbursement)]

			self.assertEqual(
				dpd_value,
				expected_dpd,
				f"DPD mismatch for {posting_date} (Disbursement: {disbursement}): Expected {expected_dpd}, got {dpd_value}",
			)

	def test_charges_payment(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			30,
			repayment_start_date="2024-10-05",
			posting_date="2024-09-15",
			rate_of_interest=10,
			applicant_type="Customer",
		)
		loan.submit()
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-09-15", repayment_start_date="2024-10-05"
		)

		# Create Charges Demand to simulate charge creation
		for i in range(0, 2):
			sales_invoice = create_sales_invoice(
				posting_date="2024-09-15", item_code="Processing Fee", qty=1, rate=1000, do_not_submit=1
			)
			sales_invoice.loan = loan.name
			sales_invoice.save()
			sales_invoice.submit()

		repayment = create_repayment_entry(
			loan.name,
			"2024-09-15",
			1000,
			repayment_type="Charge Payment",
			payable_charges=[{"charge_code": "Processing Fee", "amount": 1000}],
		)
		repayment.submit()

		self.assertEqual(repayment.total_charges_paid, 1000)
		self.assertEqual(repayment.repayment_details[0].paid_amount, 1000)

		repayment = create_repayment_entry(
			loan.name,
			"2024-09-15",
			500,
			repayment_type="Charge Payment",
			payable_charges=[{"charge_code": "Processing Fee", "amount": 500}],
		)
		repayment.submit()

		self.assertEqual(repayment.total_charges_paid, 500)
		self.assertEqual(repayment.repayment_details[0].paid_amount, 500)

	def test_accrual_background_job(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-08-16",
			posting_date="2024-08-16",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-08-16", repayment_start_date="2024-08-16"
		)

		set_loan_accrual_frequency("Daily")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-20", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan, from_date="2024-08-16", to_date="2024-08-20"
		)
		expected_dates = [
			"2024-08-16",
			"2024-08-17",
			"2024-08-18",
			"2024-08-19",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

		set_loan_accrual_frequency("Weekly")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-08-31", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan, from_date="2024-08-21", to_date="2024-08-31"
		)
		expected_dates = [
			"2024-08-25",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

		set_loan_accrual_frequency("Monthly")
		process_loan_interest_accrual_for_loans(
			loan=loan.name, posting_date="2024-10-31", company="_Test Company"
		)

		loan_interest_accruals = get_loan_interest_accrual(
			loan=loan, from_date="2024-09-01", to_date="2024-11-05"
		)
		expected_dates = [
			"2024-09-15",
			"2024-09-30",
			"2024-10-15",
		]
		expected_dates = [getdate(i) for i in expected_dates]
		accrual_dates = [getdate(i) for i in loan_interest_accruals]
		self.assertEqual(accrual_dates, expected_dates)

	def test_loc_loan_pre_payment_closure(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			2700000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-30",
			rate_of_interest=17.25,
			applicant_type="Customer",
			limit_applicable_start="2024-10-28",
			limit_applicable_end="2025-10-28",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name,
			335533,
			disbursement_date="2024-11-25",
			repayment_start_date="2025-01-24",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2025-01-23", loan=loan.name, company="_Test Company"
		)
		repayment_entry = create_repayment_entry(
			loan.name,
			"2025-01-23",
			344890,
			loan_disbursement=disbursement.name,
			repayment_type="Pre Payment",
		)
		repayment_entry.submit()

		disbursement.load_from_db()
		self.assertEqual(disbursement.status, "Closed")

		repayment_schedule_status = frappe.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "loan_disbursement": disbursement.name, "docstatus": 1},
			"status",
		)

		self.assertEqual(repayment_schedule_status, "Closed")

	def test_pre_payment_demand_booking(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			285000,
			"Repay Over Number of Periods",
			12,
			repayment_start_date="2024-12-05",
			posting_date="2024-11-07",
			rate_of_interest=17,
			applicant_type="Customer",
		)
		loan.submit()

		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-11-07", repayment_start_date="2024-12-05"
		)

		process_daily_loan_demands(posting_date="2024-12-05", loan=loan.name)

		repayment = create_repayment_entry(
			loan.name,
			"2024-12-05",
			27321,
			repayment_type="Pre Payment",
		)
		repayment.submit()

	def test_bulk_payments(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			2700000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-30",
			rate_of_interest=17.25,
			applicant_type="Customer",
			limit_applicable_start="2024-10-28",
			limit_applicable_end="2025-10-28",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name,
			335533,
			disbursement_date="2024-11-25",
			repayment_start_date="2025-01-24",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		process_loan_interest_accrual_for_loans(
			posting_date="2025-01-23", loan=loan.name, company="_Test Company"
		)

		payments = [
			{
				"doctype": "Loan Repayment",
				"against_loan": loan.name,
				"posting_date": "2025-01-20 00:10:00",
				"amount_paid": 100000,
				"loan_disbursement": disbursement.name,
			},
			{
				"doctype": "Loan Repayment",
				"against_loan": loan.name,
				"posting_date": "2025-01-21 00:10:00",
				"amount_paid": 100000,
				"loan_disbursement": disbursement.name,
			},
			{
				"doctype": "Loan Repayment",
				"against_loan": loan.name,
				"posting_date": "2025-01-22 00:10:00",
				"amount_paid": 100000,
				"loan_disbursement": disbursement.name,
			},
		]

		post_bulk_payments(payments)

	def test_npa_marking_for_customer(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		customer = frappe.get_doc(get_customer_dict("NPA Customer 1")).insert()
		frappe.db.set_value("Loan Product", "Term Loan Product 4", "days_past_due_threshold_for_npa", 90)

		loan1 = create_loan(
			customer.name,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)
		loan1.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan1.name, loan1.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)

		loan2 = create_loan(
			customer.name,
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-07-05",
			posting_date="2024-06-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan2.submit()
		# Daily accrual
		make_loan_disbursement_entry(
			loan2.name, loan2.loan_amount, disbursement_date="2024-06-05", repayment_start_date="2024-07-05"
		)

		process_daily_loan_demands(posting_date="2024-07-05", loan=loan1.name)
		create_process_loan_classification(
			posting_date="2024-07-06", loan=loan1.name, force_update_dpd_in_loan=1
		)

		loan1.load_from_db()
		loan2.load_from_db()
		customer_npa = frappe.get_value("Customer", customer.name, "is_npa")

		self.assertTrue(loan1.is_npa, "Loan 1 not marked as NPA")
		self.assertTrue(loan2.is_npa, "Loan 2 not marked as NPA")
		self.assertTrue(customer_npa, "Customer not marked as NPA")

		create_process_loan_classification(
			posting_date="2024-07-07", loan=loan1.name, force_update_dpd_in_loan=1
		)

	def test_normal_loan_repayment_schedule_close(self):
		from erpnext.selling.doctype.customer.test_customer import get_customer_dict

		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 4",
			100000,
			"Repay Over Number of Periods",
			22,
			repayment_start_date="2024-04-05",
			posting_date="2024-03-05",
			rate_of_interest=8.5,
			applicant_type="Customer",
		)

		loan.submit()

		# Daily accrual
		make_loan_disbursement_entry(
			loan.name, loan.loan_amount, disbursement_date="2024-03-05", repayment_start_date="2024-04-05"
		)

		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer 1",
				"company": "_Test Company",
				"loan": loan.name,
				"posting_date": "2025-01-15",
				"posting_time": "00:06:10",
				"set_posting_time": 1,
				"items": [{"item_code": "Processing Fee", "qty": 1, "rate": 500}],
			}
		)
		sales_invoice.submit()

		process_daily_loan_demands(posting_date="2024-04-05", loan=loan.name)

		repayment = create_repayment_entry(
			loan.name,
			"2024-04-05",
			104925,
		)

		repayment.submit()

		closed_schedule = frappe.db.get_value(
			"Loan Repayment Schedule",
			{"loan": loan.name, "docstatus": 1, "status": "Closed"},
			"name",
		)

		self.assertTrue(closed_schedule, "Repayment Schedule not closed")
		loan.load_from_db()

		# Loan will remain open because of pending charge
		self.assertEqual(loan.status, "Disbursed")

	def test_loc_loan_auto_waiver_demand_update(self):
		loan = create_loan(
			"_Test Customer 1",
			"Term Loan Product 5",
			2700000,
			"Repay Over Number of Periods",
			1,
			posting_date="2024-10-30",
			rate_of_interest=17.25,
			applicant_type="Customer",
			limit_applicable_start="2024-10-28",
			limit_applicable_end="2025-10-28",
		)
		loan.submit()

		disbursement = make_loan_disbursement_entry(
			loan.name,
			390547,
			disbursement_date="2024-10-30",
			repayment_start_date="2024-12-29",
			repayment_frequency="One Time",
		)
		disbursement.submit()

		process_daily_loan_demands(posting_date="2024-12-29", loan=loan.name)

		repayment_entry = create_repayment_entry(
			loan.name, "2024-12-29", 401621, loan_disbursement=disbursement.name
		)

		repayment_entry.submit()

		outstanding_demand = frappe.db.get_value(
			"Loan Demand",
			{"loan": loan.name, "loan_disbursement": disbursement.name},
			"sum(outstanding_amount)",
		)

		self.assertEqual(outstanding_demand, 0)
