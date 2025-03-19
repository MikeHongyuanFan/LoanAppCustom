# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanDemandOffsetOrder(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.loan_demand_offset_detail.loan_demand_offset_detail import (
			LoanDemandOffsetDetail,
		)

		components: DF.Table[LoanDemandOffsetDetail]
		title: DF.Data | None
	# end: auto-generated types

	pass
